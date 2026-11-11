# Read-only questions to SambaPOS's SQL Server, asked as the Windows user who
# is running Twilight Ledger. Twilight Ledger runs this itself; it is not
# meant to be run by hand.
#
# In:  JSON on standard input:
#        {"server": "...", "database": "...",
#         "queries": [{"name": "...", "sql": "SELECT ..."}]}
# Out: <<TWILIGHT>>{"name": [{"Column": value, ...}, ...], ...}<<END>>
#      as UTF-8 on standard output.
#
# It signs in with Windows' own login, so there is no password anywhere.
# Only a single SELECT is ever sent; anything else is refused before it
# reaches SQL Server. Dates and decimals come back as text, so nothing is
# rounded on the way.

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Data

$request = [Console]::In.ReadToEnd() | ConvertFrom-Json

$builder = New-Object System.Data.SqlClient.SqlConnectionStringBuilder
$builder['Data Source'] = [string]$request.server
$builder['Initial Catalog'] = [string]$request.database
$builder['Integrated Security'] = $true
$builder['Connect Timeout'] = 15
$builder['Application Name'] = 'Twilight Ledger (read-only)'

$culture = [System.Globalization.CultureInfo]::InvariantCulture
$connection = New-Object System.Data.SqlClient.SqlConnection $builder.ConnectionString
$connection.Open()
try {
    $answers = [ordered]@{}
    foreach ($query in $request.queries) {
        $sql = [string]$query.sql
        if ($sql -notmatch '^\s*SELECT\s' -or $sql.Contains(';')) {
            throw "Twilight Ledger only ever reads. Refused: $sql"
        }
        $command = $connection.CreateCommand()
        $command.CommandText = $sql
        $command.CommandTimeout = 60
        $reader = $command.ExecuteReader()
        $rows = New-Object System.Collections.ArrayList
        try {
            while ($reader.Read()) {
                $row = [ordered]@{}
                for ($i = 0; $i -lt $reader.FieldCount; $i++) {
                    $value = $reader.GetValue($i)
                    if ($value -is [System.DBNull]) { $value = $null }
                    elseif ($value -is [System.DateTime]) { $value = $value.ToString('yyyy-MM-ddTHH:mm:ss.fff', $culture) }
                    elseif ($value -is [System.Decimal]) { $value = $value.ToString($culture) }
                    elseif ($value -is [System.Double]) { $value = $value.ToString('R', $culture) }
                    elseif ($value -is [System.Guid]) { $value = $value.ToString() }
                    elseif ($value -is [byte[]]) { $value = $null }
                    $row[$reader.GetName($i)] = $value
                }
                [void]$rows.Add($row)
            }
        }
        finally {
            $reader.Close()
        }
        $answers[[string]$query.name] = $rows
    }
}
finally {
    $connection.Close()
}

$json = ConvertTo-Json -InputObject $answers -Depth 6 -Compress
$bytes = [System.Text.Encoding]::UTF8.GetBytes('<<TWILIGHT>>' + $json + '<<END>>')
$stdout = [Console]::OpenStandardOutput()
$stdout.Write($bytes, 0, $bytes.Length)
$stdout.Flush()
