Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
python = folder & "\.venv\Scripts\pythonw.exe"
If fso.FileExists(python) Then
    shell.CurrentDirectory = folder
    shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & folder & "\usage_widget.py" & Chr(34), 0, False
Else
    MsgBox "Run Setup.cmd in this folder first.", 64, "Usage Tracker"
End If
