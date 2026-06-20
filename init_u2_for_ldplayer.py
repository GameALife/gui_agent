"""
雷电模拟器 uiautomator2 手动初始化脚本。
跳过 init 中会失败的 IME 安装，手动安装核心组件。
"""

import os
import sys
import subprocess
import tempfile
import urllib.request
import shutil

# ADB 路径和设备地址 —— 根据实际情况修改
ADB_PATH = "adb"  # 如果PATH里没有雷电的adb，改成完整路径如 r"D:\leidian\LDPlayer9\adb.exe"
DEVICE = "127.0.0.1:5555"

# 两个必需的 APK 下载地址（GitHub releases）
APK_URLS = {
    "atx-agent": "https://github.com/openatx/uiautomator2/releases/download/2.17.0/atx-agent_2.170_linux_armv7.apk",
    "uiautomator-test": "https://github.com/openatx/uiautomator2/releases/download/2.17.0/uiautomator.apk",
}


def run_adb(args: list[str], check=True) -> str:
    """执行 adb 命令并返回输出。"""
    cmd = [ADB_PATH, "-s", DEVICE] + args
    print(f"  执行: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout.strip():
        print(f"  → {result.stdout.strip()[:200]}")
    if result.stderr.strip():
        print(f"  [stderr] {result.stderr.strip()[:200]}")
    if check and result.returncode != 0:
        print(f"  ❌ 命令失败 (code={result.returncode})")
    return result.stdout


def main():
    print("=" * 50)
    print("  雷电模拟器 uiautomator2 手动初始化")
    print("=" * 50)

    # Step 1: 确认设备在线
    print("\n[1/5] 检查设备连接...")
    output = run_adb(["get-serialno"])
    if not output.strip() or "error" in output.lower():
        print("❌ 设备未连接！请先执行:")
        print(f'   {ADB_PATH} connect {DEVICE}')
        sys.exit(1)
    print(f"✅ 设备在线: {output.strip()}")

    # Step 2: 检查已安装的包
    print("\n[2/5] 检查已安装的组件...")
    installed = run_adb(["shell", "pm", "list", "packages"])
    has_atx = "com.github.uiautomator" in installed
    has_test = "com.github.uiautomator.test" in installed
    has_ime = "com.github.uiautomator.ime" in installed
    print(f"   atx-agent (com.github.uiautomator):     {'✅ 已安装' if has_atx else '❌ 未安装'}")
    print(f"   test-app (com.github.uiautomator.test): {'✅ 已安装' if has_test else '❌ 未安装'}")
    print(f"   ime (com.github.uiautomator.ime):       {'⏭️  跳过(雷电不兼容)' if True else '...'}")

    # Step 3: 下载并安装 APK
    tmpdir = tempfile.mkdtemp(prefix="u2_init_")
    print(f"\n[3/5] 下载APK到临时目录: {tmpdir}")

    try:
        if not has_test:
            url = APK_URLS["uiautomator-test"]
            apk_path = os.path.join(tmpdir, "uiautomator.apk")
            print(f"   下载 uiautomator.apk ...")
            urllib.request.urlretrieve(url, apk_path)
            print(f"   下载完成 ({os.path.getsize(apk_path)//1024}KB)")

            print(f"   安装到模拟器...")
            # 用 -g 授予所有权限，-r 覆盖安装
            run_adb(["install", "-r", "-g", apk_path])
        else:
            print("   ⏭️  test-app 已安装，跳过")

        if not has_atx:
            url = APK_URLS["atx-agent"]
            apk_path = os.path.join(tmpdir, "atx-agent.apk")
            print(f"   下载 atx-agent.apk ...")
            urllib.request.urlretrieve(url, apk_path)
            print(f"   下载完成 ({os.path.getsize(apk_path)//1024}KB)")

            print(f"   安装到模拟器...")
            run_adb(["install", "-r", "-g", apk_path])
        else:
            print("   ⏭️  atx-agent 已安装，跳过")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Step 4: 启动 ATX Agent 服务
    print("\n[4/5] 启动 ATX Agent 服务...")
    run_adb(["shell", "am", "startservice", "-n", "com.github.uiautomator/.Service"])
    import time
    time.sleep(2)

    # Step 5: 验证
    print("\n[5/5] 验证安装...")
    installed_after = run_adb(["shell", "pm", "list", "packages"])
    has_atx_ok = "com.github.uiautomator" in installed_after
    has_test_ok = "com.github.uiautomator.test" in installed_after

    print()
    if has_atx_ok and has_test_ok:
        print("=" * 50)
        print("  ✅ 初始化完成！现在可以正常使用 uiautomator2")
        print("=" * 50)
        print()
        print("  验证命令：")
        print('    python -c "import uiautomator2 as u2; d=u2.connect(); print(d.info)"')
    else:
        print("❌ 安装可能未完全成功，请检查上面的错误信息")
        print("   常见解决方法：")
        print("   1. 雷电设置 → 开启「root权限」")
        print("   2. 雷电设置 → 关闭「读写系统分区」再重新打开")
        sys.exit(1)


if __name__ == "__main__":
    main()
