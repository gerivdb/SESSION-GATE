param(
    [Parameter(Mandatory=$true)][ValidateSet("create","push","deploy","test","info")][string]$Action,
    [string]$ProjectTitle = "MasterProxyRouter-v2",
    [string]$SourceFile = "",
    [string]$ScriptId = "",
    [string]$DeploymentId = ""
)

$ErrorActionPreference = "Stop"
$ClasprcPath = "$env:USERPROFILE\.clasprc.json"
if (-not (Test-Path $ClasprcPath)) {
    Write-Error "BLOCKED:NO_CLASPRC - Run 'clasp login' first"
    exit 1
}

$Clasprc = Get-Content $ClasprcPath -Raw | ConvertFrom-Json
$RefreshToken = $Clasprc.tokens.default.refresh_token
if (-not $RefreshToken) {
    Write-Error "BLOCKED:NO_REFRESH_TOKEN"
    exit 1
}

# Échange refresh_token → access_token
$Body = @{
    client_id     = $Clasprc.tokens.default.client_id
    client_secret = $Clasprc.tokens.default.client_secret
    refresh_token = $RefreshToken
    grant_type    = "refresh_token"
}
$TokenResp = Invoke-RestMethod -Method Post -Uri "https://oauth2.googleapis.com/token" -Body $Body
$AccessToken = $TokenResp.access_token
if (-not $AccessToken) {
    Write-Error "BLOCKED:TOKEN_EXCHANGE_FAILED"
    exit 1
}

$Headers = @{
    "Authorization" = "Bearer $AccessToken"
    "Content-Type"  = "application/json"
}

switch ($Action) {
    "create" {
        $Resp = Invoke-RestMethod -Method Post -Uri "https://script.googleapis.com/v1/projects" -Headers $Headers -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes((@{ title = $ProjectTitle } | ConvertTo-Json)))
        $Resp | ConvertTo-Json | Out-File -FilePath (Join-Path $PSScriptRoot "last_create.json") -Encoding utf8
        Write-Output ("PROJECT_CREATED:" + $Resp.scriptId)
    }
    "push" {
        if (-not $SourceFile -or -not $ScriptId) { Write-Error "MISSING:SourceFile/ScriptId"; exit 1 }
        $Source = Get-Content $SourceFile -Raw
        $Files = @(
            @{ name = "MasterProxyRouter"; type = "SERVER_JS"; source = $Source },
            @{ name = "appsscript"; type = "JSON"; source = '{"timeZone":"Europe/Paris","exceptionLogging":"STACKDRIVER","webapp":{"executeAs":"USER_DEPLOYING","access":"ANYONE_ANONYMOUS"}}' }
        )
        $BodyJson = @{ files = $Files } | ConvertTo-Json -Depth 10
        $Resp = Invoke-RestMethod -Method Put -Uri "https://script.googleapis.com/v1/projects/$ScriptId/content" -Headers $Headers -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($BodyJson))
        Write-Output "PUSH_OK"
    }
    "deploy" {
        if (-not $ScriptId) { Write-Error "MISSING:ScriptId"; exit 1 }
        $Ver = Invoke-RestMethod -Method Post -Uri "https://script.googleapis.com/v1/projects/$ScriptId/versions" -Headers $Headers -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes((@{ description = "auto-deploy" } | ConvertTo-Json)))
        $DeployBody = @{
            deploymentConfig = @{
                scriptId         = $ScriptId
                versionNumber    = $Ver.versionNumber
                manifestFileName = "appsscript"
                description      = "webapp-auto"
                webAppConfig     = @{
                    executeAs = "USER_DEPLOYING"
                    access    = "ANYONE_ANONYMOUS"
                }
            }
        } | ConvertTo-Json -Depth 10
        $Dep = Invoke-RestMethod -Method Post -Uri "https://script.googleapis.com/v1/projects/$ScriptId/deployments" -Headers $Headers -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($DeployBody))
        $Dep | ConvertTo-Json -Depth 5 | Out-File -FilePath (Join-Path $PSScriptRoot "last_deploy.json") -Encoding utf8
        Write-Output ("DEPLOYED:" + $Dep.deploymentId)
        Write-Output ("WEBAPP_URL:" + $Dep.entryPoints[0].webApp.url)
    }
    "test" {
        if (-not $ScriptId) { Write-Error "MISSING:ScriptId"; exit 1 }
        $Resp = Invoke-RestMethod -Method Get -Uri "https://script.googleapis.com/v1/projects/$ScriptId" -Headers $Headers
        Write-Output ("SCRIPT_OK:" + $Resp.title)
    }
    "info" {
        Write-Output ("CLASPRC_PATH:" + $ClasprcPath)
        Write-Output ("REFRESH_TOKEN_LEN:" + $RefreshToken.Length)
        Write-Output ("CLIENT_ID_PREFIX:" + $Clasprc.tokens.default.client_id.Substring(0,20))
    }
}
