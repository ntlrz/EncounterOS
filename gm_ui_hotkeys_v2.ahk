; AutoHotkey v2 script
#SingleInstance Force
SetTitleMatchMode "RegEx"   ; allows partial/regex matches

winTitle := "GM Control Panel"   ; must match your GM UI window title
pythonw  := "C:\Path\To\Python\pythonw.exe"  ; EDIT THIS
gmui     := "E:\HealthTracker\gm_ui.py"    ; EDIT THIS

launchIfMissing() {
    global winTitle, pythonw, gmui
    if !WinExist(winTitle) {
        try {
            Run(Format('"{1}" "{2}"', pythonw, gmui))
            WinWait(winTitle, , 5) ; wait up to 5 seconds
        } catch as err {
            MsgBox "Failed to launch GM UI:`n" err.Message
        }
    }
}

sendToGMUI(keys) {
    global winTitle
    launchIfMissing()
    try {
        ControlSend(keys,, winTitle) ; send to window even if unfocused
    } catch {
        ; swallow errors silently
    }
}

; ---- Hotkeys for Stream Deck (F13–F22) ----
F13:: sendToGMUI("c")        ; Combat toggle
F14:: sendToGMUI("{Right}")  ; Next turn
F15:: sendToGMUI("{Left}")   ; Prev turn
F16:: sendToGMUI("=")        ; HP +1
F17:: sendToGMUI("-")        ; HP -1
F18:: sendToGMUI("]")        ; HP +5
F19:: sendToGMUI("[")        ; HP -5
F20:: sendToGMUI(".")        ; Dialog next
F21:: sendToGMUI(",")        ; Dialog prev
F22:: sendToGMUI("r")        ; Reload files

; Optional: tray tip to confirm loaded
TraySetIcon("shell32.dll", 44)
; v2: TrayTip has no timeout arg. Third param = Options (1 = info icon)
TrayTip("GM UI Hotkeys", "Listening for F13–F22 and sending to GM Control Panel", 1)