import asyncio
import dataclasses
import logging
import multiprocessing
from concurrent.futures.process import ProcessPoolExecutor
from enum import Enum
from typing import Any, Callable, Dict, Optional, Set
from chia.consensus.block_record import BlockRecord
from chia.consensus.constants import ConsensusConstants
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.header_block import HeaderBlock
from chia.util.ints import uint32
from chia.util.streamable import recurse_jsonify
from chia.wallet.key_val_store import KeyValStore
from chia.wallet.wallet_block_store import WalletBlockStore
from chia.wallet.wallet_coin_store import WalletCoinStore
from chia.wallet.wallet_pool_store import WalletPoolStore
from chia.wallet.wallet_transaction_store import WalletTransactionStore

log = logging.getLogger(__name__)


class ReceiveBlockResult(Enum):
    """
    When Blockchain.receive_block(b) is called, one of these results is returned,
    showing whether the block was added to the chain (extending the peak),
    and if not, why it was not added.
    """

    NEW_PEAK = 1  # Added to the peak of the blockchain
    ADDED_AS_ORPHAN = 2  # Added as an orphan/stale block (not a new peak of the chain)
    INVALID_BLOCK = 3  # Block was not added because it was invalid
    ALREADY_HAVE_BLOCK = 4  # Block is already present in this blockchain
    DISCONNECTED_BLOCK = 5  # Block's parent (previous pointer) is not in this blockchain


class SimpleWalletBlockchain:
    constants: ConsensusConstants
    constants_json: Dict
    # peak of the blockchain
    _peak_height: Optional[uint32]
    # All blocks in peak path are guaranteed to be included, can include orphan blocks
    __block_records: Dict[bytes32, BlockRecord]
    # Defines the path from genesis to the peak, no orphan blocks
    __height_to_hash: Dict[uint32, bytes32]
    # all hashes of blocks in block_record by height, used for garbage collection
    __heights_in_cache: Dict[uint32, Set[bytes32]]
    # All sub-epoch summaries that have been included in the blockchain from the beginning until and including the peak
    # (height_included, SubEpochSummary). Note: ONLY for the blocks in the path to the peak
    __sub_epoch_summaries: Dict[uint32, SubEpochSummary] = {}
    # Stores
    coin_store: WalletCoinStore
    tx_store: WalletTransactionStore
    pool_store: WalletPoolStore
    block_store: WalletBlockStore
    # Used to verify blocks in parallel
    pool: ProcessPoolExecutor

    new_transaction_block_callback: Any
    reorg_rollback: Any
    wallet_state_manager_lock: asyncio.Lock

    # Whether blockchain is shut down or not
    _shut_down: bool

    # Lock to prevent simultaneous reads and writes
    lock: asyncio.Lock
    log: logging.Logger
    basic_store: KeyValStore
    latest_tx_block: Optional[HeaderBlock]
    peak: Optional[HeaderBlock]

    @staticmethod
    async def create(basic_store: KeyValStore):
        """
        Initializes a blockchain with the BlockRecords from disk, assuming they have all been
        validated. Uses the genesis block given in override_constants, or as a fallback,
        in the consensus constants config.
        """
        self = SimpleWalletBlockchain()
        self.basic_store = basic_store
        stored_height = await self.basic_store.get_str("STORED_HEIGHT")
        self.latest_tx_block = None
        self.latest_tx_block = await self.get_latest_tx_block()
        self.peak = None
        self.peak = await self.get_peak_block()
        if stored_height is None:
            self._peak_height = 0
        else:
            self._peak_height = int(stored_height)
        return self

    async def set_peak_height(self, height):
        self._peak_height = height
        await self.basic_store.set_str("STORED_HEIGHT", f"{height}")

    def get_peak_height(self) -> Optional[uint32]:
        return self._peak_height

    async def set_latest_tx_block(self, block: HeaderBlock):
        await self.basic_store.set_object("LATEST_TX_BLOCK", block)
        self.latest_tx_block = block

    async def get_latest_tx_block(self) -> Optional[HeaderBlock]:
        if self.latest_tx_block is not None:
            return self.latest_tx_block
        obj = await self.basic_store.get_object("LATEST_TX_BLOCK", HeaderBlock)
        return obj

    async def set_peak_block(self, block: HeaderBlock):
        await self.basic_store.set_object("PEAK_BLOCK", block)
        self.peak = block

    async def get_peak_block(self) -> Optional[HeaderBlock]:
        if self.peak is not None:
            return self.peak
        obj = await self.basic_store.get_object("PEAK_BLOCK", HeaderBlock)
        return obj
