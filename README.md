generate binary wheel install file for python project

params:
  - --project-root PATH：源代码所在工程根目录，脚本会在这里找到待处理的包（默认无；必填）。
  - --packages PKG [PKG …]：要编译的包名（可多个，采用点号路径，如 txs_mf_stat）；脚本会把它们复制到临时构建区。
  - --python-bin PATH：用于执行 Cython 与编译的 Python 解释器（需带开发环境、Cython、setuptools），例 /home/.../py312/bin/python。
  - --wheel-name NAME：生成的发行包名称（决定 wheel/tar.gz 前缀），如 txs_mf_stat_binary。
  - --version VERSION：发行版本号，写入 wheel 元数据与 tar 包文件名。
  - --output-dir DIR：最终成果存放目录（默认 dist）。脚本会在其中创建临时构建区与输出文件。
  - --python-tag TAG：PEP 425 wheel 的 Python 版本标记，默认 cp312。
  - --skip-tarball：设置后跳过生成额外的 wheel_name-version-binary.tar.gz 压缩包，仅生成 wheel。


example:
    python dist/build_binary_wheel.py \
        --project-root . \
        --packages txs_mf_stat \
        --python-bin /home/ansonxiang/miniconda3/envs/py312/bin/python \
        --wheel-name txs_mf_stat_binary \
        --version 0.1.0 \
        --output-dir dist

 python build_binary_wheel.py \
    --project-root /home/ansonxiang/git/TXS_MF_Stat \
    --packages txs_mf_stat \
    --python-bin /home/ansonxiang/miniconda3/envs/py312/bin/python \
    --wheel-name txs_mf_stat \
    --version 0.1.1 \
    --output-dir /home/ansonxiang/git/TXS_MF_Stat/dist        

 python build_binary_wheel.py \
    --project-root /home/ansonxiang/git/spec_layer/ \
    --packages spec_layer \
    --python-bin /home/ansonxiang/miniconda3/envs/py312/bin/python \
    --wheel-name spec_layer \
    --version 0.1.1 \
    --output-dir /home/ansonxiang/git/spec_layer/dist        

 python build_binary_wheel.py \
    --project-root /home/ansonxiang/git/spec_db/ \
    --packages spec_db \
    --python-bin /home/ansonxiang/miniconda3/envs/py312/bin/python \
    --wheel-name spec_db \
    --version 0.1.1 \
    --output-dir /home/ansonxiang/git/spec_db/dist        


    /home/ansonxiang/git/TXS_MF_Stat/txs_mf_stat