' DeepSeek sync bridge -- start automatically at logon (no console window).
' To disable: delete this file from the Windows Startup folder.
' To stop the service right now: run stop.cmd

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

profile = shell.ExpandEnvironmentStrings("%USERPROFILE%")
python = profile & "\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
backend = profile & "\Documents\ChatGPT\New project\tools\deepseek_bridge\server.py"

If Not fso.FileExists(python) Then
    python = "python"
End If

If Not fso.FileExists(backend) Then
    WScript.Quit
End If

' 0 = hidden window, False = do not wait for it to finish
shell.Run """" & python & """ """ & backend & """", 0, False
