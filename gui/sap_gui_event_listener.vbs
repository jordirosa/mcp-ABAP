Option Explicit

Dim fso
Set fso = CreateObject("Scripting.FileSystemObject")

Dim targetSessionId
Dim outputFolder
Dim screenshotsFolder
Dim stopFilePath
Dim readyFilePath
Dim eventsFilePath
Dim logFilePath
Dim captureIndex
Dim tempFolder
Dim targetSession

captureIndex = 0

If WScript.Arguments.Count < 2 Then
    WScript.Quit 1
End If

targetSessionId = CStr(WScript.Arguments(0))
outputFolder = CStr(WScript.Arguments(1))
tempFolder = fso.BuildPath(outputFolder, ".tmp")
screenshotsFolder = fso.BuildPath(tempFolder, "raw_screenshots")
stopFilePath = fso.BuildPath(tempFolder, "listener.stop")
readyFilePath = fso.BuildPath(tempFolder, "listener.ready")
eventsFilePath = fso.BuildPath(tempFolder, "events.jsonl")
logFilePath = fso.BuildPath(outputFolder, "logs\listener.log")

EnsureFolder outputFolder
EnsureFolder tempFolder
EnsureFolder screenshotsFolder
EnsureFolder fso.BuildPath(outputFolder, "logs")
DeleteIfExists readyFilePath
DeleteIfExists stopFilePath

Dim sapGui
Dim application
Set sapGui = GetObject("SAPGUI")
Set application = sapGui.GetScriptingEngine
Set targetSession = FindSessionById(application, targetSessionId)

If targetSession Is Nothing Then
    WriteLog "Target session not found: " & targetSessionId
    WScript.Quit 2
End If

WriteLog "Target session attached: " & targetSessionId
WScript.ConnectObject targetSession, "Sess_"
CreateEmptyFile readyFilePath
WriteLog "Event listener ready."

Do While Not fso.FileExists(stopFilePath)
    WScript.Sleep 200
Loop

WriteLog "Stop signal detected."

Sub Sess_Change(ByVal Session, ByVal Component, ByVal CommandArray)
    On Error Resume Next
    WriteEvent "change", Session, Component, ""
    CaptureScreenshot Session, "before"
End Sub

Sub Sess_StartRequest(ByVal Session)
    On Error Resume Next
    WriteEvent "startRequest", Session, Nothing, ""
End Sub

Sub Sess_EndRequest(ByVal Session)
    On Error Resume Next
    WriteEvent "endRequest", Session, Nothing, ""
    CaptureScreenshot Session, "after"
End Sub

Sub Sess_ProgressIndicator(ByVal percentage, ByVal Text)
    On Error Resume Next
    WriteProgress percentage, Text
End Sub

Sub Sess_Error(ByVal Session, ByVal ErrorId, ByVal Desc1, ByVal Desc2, ByVal Desc3, ByVal Desc4)
    On Error Resume Next
    WriteLog "Session error id=" & CStr(ErrorId) & " desc1=" & Desc1 & " desc2=" & Desc2 & " desc3=" & Desc3 & " desc4=" & Desc4
End Sub

Function FindSessionById(ByVal application, ByVal sessionId)
    Dim connectionIndex
    Dim sessionIndex
    Dim connection
    Dim session

    Set FindSessionById = Nothing
    For connectionIndex = 0 To application.Children.Count - 1
        Set connection = application.Children.Item(CLng(connectionIndex))
        For sessionIndex = 0 To connection.Children.Count - 1
            Set session = connection.Children.Item(CLng(sessionIndex))
            If CStr(session.Id) = sessionId Then
                Set FindSessionById = session
                Exit Function
            End If
        Next
    Next
End Function

Sub CaptureScreenshot(ByVal Session, ByVal phase)
    On Error Resume Next
    captureIndex = captureIndex + 1

    Dim captureGroupId
    Dim programName
    Dim screenNumber
    Dim childIndex
    Dim windowObject
    Dim windowId
    Dim windowName
    Dim fileName
    Dim fullPath

    captureGroupId = PadNumber(captureIndex, 4)
    programName = SafeFilePart(Session.Info.Program)
    screenNumber = SafeFilePart(Session.Info.ScreenNumber)
    If programName = "" Then programName = "unknown_program"
    If screenNumber = "" Then screenNumber = "unknown_screen"

    For childIndex = 0 To Session.Children.Count - 1
        Set windowObject = Session.Children.Item(CLng(childIndex))
        windowId = SafeValue(windowObject.Id)
        If InStr(windowId, "/wnd[") > 0 Then
            windowName = SafeFilePart(Replace(Replace(windowId, "/", "_"), "[", "_"))
            fileName = captureGroupId & "_" & phase & "_" & programName & "_" & screenNumber & "_" & windowName & ".bmp"
            fullPath = fso.BuildPath(screenshotsFolder, fileName)
            windowObject.HardCopy fullPath, 2
            WriteScreenshotEvent Session, phase, captureGroupId, windowObject, ".tmp/raw_screenshots/" & fileName
        End If
    Next
End Sub

Sub WriteProgress(ByVal percentage, ByVal textValue)
    Dim line
    line = "{""eventType"":""progressIndicator"",""percentage"":" & CStr(percentage) & ",""text"":""" & JsonEscape(CStr(textValue)) & """}"
    AppendLine eventsFilePath, line
End Sub

Sub WriteScreenshotEvent(ByVal Session, ByVal phase, ByVal captureGroupId, ByVal WindowObject, ByVal screenshotFile)
    Dim leftValue
    Dim topValue
    Dim widthValue
    Dim heightValue
    Dim line

    leftValue = SafeNumber(GetNumericProperty(WindowObject, "ScreenLeft"))
    If leftValue = "" Then leftValue = SafeNumber(GetNumericProperty(WindowObject, "Left"))
    topValue = SafeNumber(GetNumericProperty(WindowObject, "ScreenTop"))
    If topValue = "" Then topValue = SafeNumber(GetNumericProperty(WindowObject, "Top"))
    widthValue = SafeNumber(GetNumericProperty(WindowObject, "Width"))
    heightValue = SafeNumber(GetNumericProperty(WindowObject, "Height"))

    line = "{""eventType"":""screenshotWindow""," & _
        """timestamp"":""" & JsonEscape(NowIso()) & """," & _
        """captureGroupId"":""" & JsonEscape(captureGroupId) & """," & _
        """phase"":""" & JsonEscape(phase) & """," & _
        """sessionId"":""" & JsonEscape(targetSessionId) & """," & _
        """windowId"":""" & JsonEscape(SafeValue(WindowObject.Id)) & """," & _
        """windowType"":""" & JsonEscape(SafeValue(WindowObject.Type)) & """," & _
        """windowText"":""" & JsonEscape(SafeValue(WindowObject.Text)) & """," & _
        """left"":" & leftValue & "," & _
        """top"":" & topValue & "," & _
        """width"":" & widthValue & "," & _
        """height"":" & heightValue & "," & _
        """transaction"":""" & JsonEscape(SafeValue(Session.Info.Transaction)) & """," & _
        """program"":""" & JsonEscape(SafeValue(Session.Info.Program)) & """," & _
        """screenNumber"":""" & JsonEscape(SafeValue(Session.Info.ScreenNumber)) & """," & _
        """windowTitle"":""" & JsonEscape(SafeValue(Session.FindById("wnd[0]").Text)) & """," & _
        """screenshotFile"":""" & JsonEscape(screenshotFile) & """}"
    AppendLine eventsFilePath, line
End Sub

Sub WriteEvent(ByVal eventType, ByVal Session, ByVal Component, ByVal screenshotFile)
    Dim componentId
    Dim componentType
    Dim transaction
    Dim programName
    Dim screenNumber
    Dim windowTitle
    Dim line

    componentId = ""
    componentType = ""
    If Not (Component Is Nothing) Then
        componentId = CStr(Component.Id)
        componentType = CStr(Component.Type)
    End If

    transaction = ""
    programName = ""
    screenNumber = ""
    windowTitle = ""
    If Not (Session Is Nothing) Then
        transaction = SafeValue(Session.Info.Transaction)
        programName = SafeValue(Session.Info.Program)
        screenNumber = SafeValue(Session.Info.ScreenNumber)
        windowTitle = SafeValue(Session.FindById("wnd[0]").Text)
    End If

    line = "{""eventType"":""" & JsonEscape(eventType) & """," & _
        """timestamp"":""" & JsonEscape(NowIso()) & """," & _
        """sessionId"":""" & JsonEscape(targetSessionId) & """," & _
        """componentId"":""" & JsonEscape(componentId) & """," & _
        """componentType"":""" & JsonEscape(componentType) & """," & _
        """transaction"":""" & JsonEscape(transaction) & """," & _
        """program"":""" & JsonEscape(programName) & """," & _
        """screenNumber"":""" & JsonEscape(screenNumber) & """," & _
        """windowTitle"":""" & JsonEscape(windowTitle) & """," & _
        """screenshotFile"":""" & JsonEscape(screenshotFile) & """}"
    AppendLine eventsFilePath, line
End Sub

Function SafeValue(ByVal value)
    On Error Resume Next
    SafeValue = ""
    If IsNull(value) Then Exit Function
    SafeValue = CStr(value)
End Function

Function GetNumericProperty(ByVal target, ByVal propertyName)
    On Error Resume Next
    Err.Clear
    Select Case propertyName
        Case "ScreenLeft"
            GetNumericProperty = target.ScreenLeft
        Case "ScreenTop"
            GetNumericProperty = target.ScreenTop
        Case "Left"
            GetNumericProperty = target.Left
        Case "Top"
            GetNumericProperty = target.Top
        Case "Width"
            GetNumericProperty = target.Width
        Case "Height"
            GetNumericProperty = target.Height
        Case Else
            GetNumericProperty = ""
    End Select
    If Err.Number <> 0 Then
        Err.Clear
        GetNumericProperty = ""
    End If
End Function

Function SafeNumber(ByVal value)
    On Error Resume Next
    If IsNumeric(value) Then
        SafeNumber = CStr(CLng(value))
    Else
        SafeNumber = "0"
    End If
End Function

Function SafeFilePart(ByVal value)
    Dim textValue
    Dim i
    Dim result
    Dim ch

    textValue = SafeValue(value)
    result = ""
    For i = 1 To Len(textValue)
        ch = Mid(textValue, i, 1)
        If (ch >= "0" And ch <= "9") Or (ch >= "A" And ch <= "Z") Or (ch >= "a" And ch <= "z") Or ch = "_" Or ch = "-" Then
            result = result & ch
        Else
            result = result & "_"
        End If
    Next
    SafeFilePart = result
End Function

Function PadNumber(ByVal value, ByVal width)
    Dim textValue
    textValue = CStr(value)
    Do While Len(textValue) < width
        textValue = "0" & textValue
    Loop
    PadNumber = textValue
End Function

Function JsonEscape(ByVal value)
    Dim result
    result = CStr(value)
    result = Replace(result, "\", "\\")
    result = Replace(result, """", "\""")
    result = Replace(result, vbCrLf, "\n")
    result = Replace(result, vbCr, "\n")
    result = Replace(result, vbLf, "\n")
    JsonEscape = result
End Function

Function NowIso()
    Dim dt
    dt = Now
    NowIso = Year(dt) & "-" & PadNumber(Month(dt), 2) & "-" & PadNumber(Day(dt), 2) & _
        "T" & PadNumber(Hour(dt), 2) & ":" & PadNumber(Minute(dt), 2) & ":" & PadNumber(Second(dt), 2)
End Function

Sub EnsureFolder(ByVal folderPath)
    If Not fso.FolderExists(folderPath) Then
        fso.CreateFolder folderPath
    End If
End Sub

Sub DeleteIfExists(ByVal filePath)
    If fso.FileExists(filePath) Then
        fso.DeleteFile filePath, True
    End If
End Sub

Sub CreateEmptyFile(ByVal filePath)
    Dim stream
    Set stream = fso.CreateTextFile(filePath, True, True)
    stream.Close
End Sub

Sub AppendLine(ByVal filePath, ByVal line)
    Dim stream
    Set stream = fso.OpenTextFile(filePath, 8, True, -1)
    stream.WriteLine line
    stream.Close
End Sub

Sub WriteLog(ByVal message)
    AppendLine logFilePath, "[" & NowIso() & "] " & message
End Sub
