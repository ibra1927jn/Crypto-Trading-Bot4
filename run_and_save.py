import subprocess
with open('clean_output.txt', 'w', encoding='utf-8') as f:
    result = subprocess.run(['venv\\\\Scripts\\\\python.exe', 'check_all.py'], capture_output=True, text=True, cwd=r'c:\\Users\\ibrab\\Desktop\\Crypto-Trading-Bot4')
    f.write(result.stdout)
    f.write(result.stderr)
print("Saved cleanly.")
