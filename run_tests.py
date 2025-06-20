#!/usr/bin/env python
"""
測試執行器

支援運行不同類型的測試：單元測試、整合測試等
"""
import os
import sys
import argparse
import subprocess
from pathlib import Path

def run_command(cmd, description=""):
    """執行命令並處理結果"""
    print(f"\n{'='*60}")
    print(f"執行: {description or cmd}")
    print(f"{'='*60}")
    
    result = subprocess.run(cmd, shell=True, capture_output=False)
    
    if result.returncode != 0:
        print(f"\n❌ 測試失敗: {description}")
        return False
    else:
        print(f"\n✅ 測試通過: {description}")
        return True

def run_unit_tests(test_filter=None, disable_warnings=True):
    """運行單元測試"""
    cmd = "python -m pytest tests/unit/ -v"
    if disable_warnings:
        cmd = f"PYTHONWARNINGS=ignore {cmd}"
    if test_filter:
        cmd += f" -k {test_filter}"
    
    return run_command(cmd, "單元測試")

def run_integration_tests(test_filter=None, disable_warnings=False):
    """運行整合測試"""
    cmd = "python -m pytest tests/integration/ -v -s"  # 添加 -s 參數顯示日誌
    if disable_warnings:
        cmd = f"PYTHONWARNINGS=ignore {cmd}"
    if test_filter:
        cmd += f" -k {test_filter}"
    
    return run_command(cmd, "整合測試")

def run_fubon_tests(test_type="all"):
    """運行富邦相關測試"""
    if test_type == "unit":
        cmd = "PYTHONWARNINGS=ignore python -m pytest tests/unit/test_fubon_account_unit.py -v"
        description = "富邦帳戶單元測試"
    elif test_type == "integration":
        cmd = "python -m pytest tests/integration/test_fubon_account_integration.py -v -s"  # 添加 -s 參數
        description = "富邦帳戶整合測試"
    else:
        cmd = "PYTHONWARNINGS=ignore python -m pytest tests/unit/test_fubon_account_unit.py tests/integration/test_fubon_account_integration.py -v -s"
        description = "富邦帳戶所有測試"
    
    return run_command(cmd, description)

def run_legacy_tests():
    """運行舊的測試檔案"""
    legacy_files = [
        "test_fubon_account.py",
        "test_fugle_account.py", 
        "test_masterlink_account.py",
        "test.py"
    ]
    
    success = True
    for test_file in legacy_files:
        if os.path.exists(test_file):
            cmd = f"python -m unittest {test_file.replace('.py', '')}"
            result = run_command(cmd, f"舊版測試: {test_file}")
            success = success and result
    
    return success

def run_specific_test(test_path):
    """運行特定測試"""
    cmd = f"python -m pytest {test_path} -v -s"  # 添加 -s 參數
    return run_command(cmd, f"特定測試: {test_path}")

def check_environment():
    """檢查測試環境"""
    print("檢查測試環境...")
    
    # 檢查富邦憑證
    fubon_vars = [
        "FUBON_NATIONAL_ID",
        "FUBON_ACCOUNT_PASS", 
        "FUBON_CERT_PATH"
    ]
    
    fubon_ready = all(os.environ.get(var) for var in fubon_vars)
    
    print(f"富邦證券測試環境: {'✅ 已配置' if fubon_ready else '❌ 未配置'}")
    
    if not fubon_ready:
        print("  缺少環境變數:")
        for var in fubon_vars:
            status = "✅" if os.environ.get(var) else "❌"
            print(f"    {status} {var}")
    
    print(f"測試目錄: {'✅ 存在' if os.path.exists('tests') else '❌ 不存在'}")
    
    return fubon_ready

def main():
    parser = argparse.ArgumentParser(description="Order Executor 測試執行器")
    
    parser.add_argument("--all", action="store_true", help="運行所有測試")
    parser.add_argument("--unit", action="store_true", help="運行單元測試")
    parser.add_argument("--integration", action="store_true", help="運行整合測試")
    parser.add_argument("--fubon", choices=["unit", "integration", "all"], 
                       help="運行富邦帳戶測試")
    parser.add_argument("--legacy", action="store_true", help="運行舊版測試")
    parser.add_argument("--test", type=str, help="運行特定測試 (pytest 路徑)")
    parser.add_argument("--filter", type=str, help="測試過濾器")
    parser.add_argument("--env-check", action="store_true", help="檢查測試環境")
    parser.add_argument("--verbose", "-v", action="store_true", help="詳細輸出")
    
    args = parser.parse_args()
    
    # 確保在正確的目錄中
    script_dir = Path(__file__).parent
    os.chdir(script_dir)
    
    # 檢查環境
    if args.env_check:
        check_environment()
        return
    
    success = True
    
    # 運行特定測試
    if args.test:
        success = run_specific_test(args.test)
    
    # 運行富邦測試
    elif args.fubon:
        success = run_fubon_tests(args.fubon)
    
    # 運行單元測試
    elif args.unit:
        success = run_unit_tests(args.filter)
    
    # 運行整合測試
    elif args.integration:
        success = run_integration_tests(args.filter)
    
    # 運行舊版測試
    elif args.legacy:
        success = run_legacy_tests()
    
    # 運行所有測試
    elif args.all:
        print("運行所有測試...")
        check_environment()
        
        results = []
        results.append(run_unit_tests())
        results.append(run_integration_tests(disable_warnings=False))  # 整合測試顯示日誌
        
        success = all(results)
        
        print(f"\n{'='*60}")
        print("測試總結:")
        print(f"單元測試: {'✅ 通過' if results[0] else '❌ 失敗'}")
        print(f"整合測試: {'✅ 通過' if results[1] else '❌ 失敗'}")
        print(f"整體結果: {'✅ 所有測試通過' if success else '❌ 有測試失敗'}")
        print(f"{'='*60}")
    
    else:
        # 默認運行單元測試
        print("未指定測試類型，運行單元測試...")
        success = run_unit_tests()
    
    # 退出碼
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()