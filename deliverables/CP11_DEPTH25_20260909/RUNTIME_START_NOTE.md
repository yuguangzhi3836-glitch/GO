# 还原后的运行说明

1906个还原文件及1051个冻结源码SHA256均通过第二次独立核对。本环境在还原器完成后，Python权限位读为0644；不能声称可执行权限跨执行保持。源码字节一致，完整回归使用已核验的父级Python运行时完成。

在自己的Linux还原目录中，运行前显式执行：

```sh
chmod +x gate_runtime/python/bin/python gate_runtime/python/bin/python3 gate_runtime/python/bin/python3.13
gate_runtime/python/bin/python scripts/run_local_demo.py --check
gate_runtime/python/bin/python scripts/run_local_demo.py
```

本包为工程验收交付，FINAL_RELEASE_GATE仍为HOLD。运行验收、封包完整性和全系统验收分别记录。
