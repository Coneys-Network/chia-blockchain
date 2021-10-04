git clone https://github.com/cangoosechain/chia-blockchain.git
git checkout dev

./install.sh
./install-timelord.sh

. ./activate

# 可以看到python虚拟环境已经启动，命令行签名出现 (env)
chia init

chia start timelord

chia start introducer

# introducer 和 timelord可以放在一台机器上，introducer就是类似整个网络的节点广播器



#单独开一个窗口，
df -h # 列出所有的硬盘信息，找到对应的硬盘
sudo mount /dev/sdb2 /media/plota # 将硬盘mount到对应的目录，

#回到chia窗口，前面有（env）的这个，保证所有的硬盘被mount到对应的目录之后，执行如下语句
chia plots add -d /media/plota/PPlots/

chia start farmer