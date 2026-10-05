$secret = "" | ConvertTo-SecureString -AsPlainText -Force
$env:WEB_IQ_API_KEY = [System.Net.NetworkCredential]::new("", $secret).Password
Remove-Variable secret