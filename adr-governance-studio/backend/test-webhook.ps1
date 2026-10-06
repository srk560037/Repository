# ==============================================================================
# Script: test-webhook.ps1
# Description: Generates HMAC SHA-256 signature and tests GitHub Webhook endpoint
# ==============================================================================

$endpoint = "http://127.0.0.1:8000/v1/webhooks/github"
$secret   = "local_adr_dev_secret_123"  # Must match GITHUB_WEBHOOK_SECRET in main.py

# 1. Construct Mock GitHub Pull Request Payload
$payloadObject = @{
    action = "opened"
    number = 42
    pull_request = @{
        id = 12345678
        title = "ADR-001: Adopt Kafka for Event Streaming"
        state = "open"
        url   = "https://api.github.com/repos/my-org/my-repo/pulls/42"
    }
    repository = @{
        name = "adr-governance-studio"
        full_name = "my-org/adr-governance-studio"
    }
}

# Convert payload to compact JSON (exact string representation needed for HMAC)
$jsonPayload =$payloadObject | ConvertTo-Json -Depth 5 -Compress

# 2. Compute HMAC SHA-256 Signature
$encoding = [System.Text.Encoding]::UTF8
$secretBytes  =$encoding.GetBytes($secret)$payloadBytes = $encoding.GetBytes($jsonPayload)

$hmac = New-Object System.Security.Cryptography.HMACSHA256
$hmac.Key = $secretBytes$hashBytes = $hmac.ComputeHash($payloadBytes)

$signature = "sha256=" + [System.BitConverter]::ToString($hashBytes).Replace("-", "").ToLower()

# 3. Construct HTTP Request Headers
$headers = @{
    "X-GitHub-Event"       = "pull_request"
    "X-Hub-Signature-256"  = $signature
}

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " Sending Mock Webhook to $endpoint " -ForegroundColor Cyan
Write-Host " Signature: $signature" -ForegroundColor DarkGray
Write-Host "==========================================" -ForegroundColor Cyan

# 4. Dispatch Webhook Request
try {
    $response = Invoke-RestMethod -Uri$endpoint -Method Post -Body $payloadBytes -ContentType "application/json" -Headers $headers
    Write-Host "`nSUCCESS! Server Response:" -ForegroundColor Green
    $response | ConvertTo-Json -Depth 5
}
catch {
    Write-Host "`nFAILED! Exception Details:" -ForegroundColor Red
    $_ .Exception.Message
    if ($_.Exception.Response) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        Write-Host "Response Body: " $reader.ReadToEnd() -ForegroundColor Yellow
    }
}