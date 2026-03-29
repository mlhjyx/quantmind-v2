$logFile = "D:\quantmind-v2\scripts\verify_tasks_result.txt"
$result = ""

# Search all task folders
$ts = New-Object -ComObject Schedule.Service
$ts.Connect()

function SearchFolder($folder, $pattern) {
    $global:result = $result
    foreach ($task in $folder.GetTasks(0)) {
        if ($task.Name -like $pattern) {
            $global:result += "Path: $($task.Path)`r`n"
            $global:result += "Name: $($task.Name)`r`n"
            $global:result += "State: $($task.State)`r`n"
            $global:result += "NextRun: $($task.NextRunTime)`r`n"
            $global:result += "LastRun: $($task.LastRunTime)`r`n"
            $def = $task.Definition
            $global:result += "Execute: $($def.Actions.Item(1).Path)`r`n"
            $global:result += "Args: $($def.Actions.Item(1).Arguments)`r`n"
            $global:result += "WorkDir: $($def.Actions.Item(1).WorkingDirectory)`r`n"
            $global:result += "Description: $($def.RegistrationInfo.Description)`r`n"
            $global:result += "---`r`n"
        }
    }
    foreach ($subfolder in $folder.GetFolders(0)) {
        SearchFolder $subfolder $pattern
    }
}

SearchFolder ($ts.GetFolder("\")) "*QuantMind*"
if ($result -eq "") { $result = "NO TASKS FOUND ANYWHERE" }
[System.IO.File]::WriteAllText($logFile, $result, [System.Text.Encoding]::UTF8)
