Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "C:\Users\thoma\OneDrive\Documentos\Codex\2026-09-24\es\work\Meet2Notes"
shell.Run "C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File ""C:\Users\thoma\OneDrive\Documentos\Codex\2026-09-24\es\work\Meet2Notes\tray.ps1""", 0, False
