' Run a batch file with no console window, forwarding all arguments.
' Usage: wscript.exe //nologo launch-hidden.vbs "<path-to-bat>" [args...]
' The whole command line is wrapped once so args with spaces survive cmd /c quoting.
Dim cmd, i
cmd = """" & WScript.Arguments(0) & """"
For i = 1 To WScript.Arguments.Count - 1
    cmd = cmd & " """ & WScript.Arguments(i) & """"
Next
CreateObject("WScript.Shell").Run "cmd.exe /c """ & cmd & """", 0, False
