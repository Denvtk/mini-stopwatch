' Tihiy zapusk sekundomera: bez okna konsoli.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "pythonw.exe """ & folder & "\secundomer.py""", 0, False
