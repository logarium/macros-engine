@echo off
cd /d "%~dp0"

:: Free port 8000 if anything is using it
C:\Python314\python.exe -c "import subprocess, re, os; out=subprocess.run(['netstat','-ano'],capture_output=True,text=True).stdout; pids={m.group(1) for m in re.finditer(r':8000\s+\S+\s+LISTENING\s+(\d+)',out)}; [os.kill(int(p),9) for p in pids if int(p)>0]"

timeout /t 1 /nobreak >nul

start "" /b C:\Python314\pythonw.exe gammaria.py
exit
