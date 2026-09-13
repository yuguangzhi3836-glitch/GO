# DEPTH46 合并父包

基于 PR47 DEPTH45 已验应用树，包含 1311 个完整业务源码文件、重新构建并离线恢复的运行镜像、19 个保留的部署兼容文件、冻结 Python 依赖及各轮原始证据。酒店改期无手续费、一年固定期限、贵补差价便宜不退规则保留。

PR51 部署请求入口及其依赖源码保存在 supplements/PR51，并附固定提交、逐文件哈希和本包内重新运行的 35+22 项隔离检查。默认部署开关关闭；这部分是待安装源码，未并入业务镜像或自动启用。

PARENT_MANIFEST.json 绑定应用源码树、打包提交、原始验收提交和运行镜像。应用测试仍绑定其真实固定源码，部署请求入口的检查仅代表隔离模拟器。香港和 Production 保持 HOLD。

下载永久交付目录的全部分卷后执行：

    python3 reconstruct_parent.py --directory . --output CP11_DEPTH46_CONSOLIDATED_PARENT_20260913.zip
    python3 verify_parent.py --zip CP11_DEPTH46_CONSOLIDATED_PARENT_20260913.zip --sha256 <发布的完整SHA256> --restore-to restored-parent

恢复过程只复制到全新目录，不安装、启动镜像或部署。后续开发以 PR47 application/ 继续，保留完整源码历史。
