@echo off
rem 这两个是这台机器上实际可用的路径。
rem 用法：在这个命令行里跑一次 setup_env.bat，或者把它加到开机项。
set "GH_PATH=E:\Apps\GitHub CLI\bin\gh.exe"
set "GIT_PATH=C:\Users\褚富兴\PortableGit\cmd\git.exe"
echo GH_PATH=%GH_PATH%
echo GIT_PATH=%GIT_PATH%
echo.
echo 当前窗口已生效。新开的窗口需要重新跑一次。
