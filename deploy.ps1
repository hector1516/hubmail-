param(
    [string]$RemoteDir = "C:/Users/eccsa/hubmail",
    [string]$ImageName = "eccsa/hubmail",
    [string]$ContainerName = "hubmail",
    [string]$DbName = "HUBMAIL",
    [string]$DbServer = "172.26.90.159",
    [string]$DbUser = "hubmail",
    [string]$DbPassword = "eyccazo",
    [string]$UsersDbName = "ECCSA_Admon_Pruebas",
    [string]$UsersDbServer = "172.26.117.220"
)

$plink = "C:\Program Files\HeidiSQL\plink.exe"
$hostkey = "SHA256:QClufJSyrTFwVoHmdc1hZTT8k3A/cWYiXMUKICF1iTc"
$user = "eccsa@172.26.90.159"
$pw = "eyccazo"
$localRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Invoke-Remote([string]$cmd) {
    & $plink -batch -ssh $user -pw $pw -hostkey $hostkey $cmd
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR remoto (exit $LASTEXITCODE): $cmd" -ForegroundColor Red; exit 1 }
}

function Upload-File([string]$local, [string]$remote) {
    $b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($local))
    $b64 | & $plink -batch -ssh $user -pw $pw -hostkey $hostkey "python C:\Users\eccsa\upload.py $remote"
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR upload: $remote" -ForegroundColor Red; exit 1 }
}

# uploader remoto (bootstrap sin comillas dobles)
$uploadPy = Get-Content -Raw -Encoding UTF8 "$PSScriptRoot\.upload_helper.py"
$b64Up = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($uploadPy))
Invoke-Remote "python -c open(r'C:\Users\eccsa\upload.py','wb').write(__import__('base64').b64decode(r'$b64Up'))"

Write-Host "==> 1/6 Creando directorio remoto"
Invoke-Remote "if not exist C:\Users\eccsa\hubmail mkdir C:\Users\eccsa\hubmail"
Invoke-Remote "if not exist C:\Users\eccsa\hubmail\app mkdir C:\Users\eccsa\hubmail\app"
Invoke-Remote "if not exist C:\Users\eccsa\hubmail\static mkdir C:\Users\eccsa\hubmail\static"
Invoke-Remote "if not exist C:\Users\eccsa\hubmail\migrations_mysql mkdir C:\Users\eccsa\hubmail\migrations_mysql"

Write-Host "==> 2/6 Subiendo codigo"
Upload-File "$localRoot\app\main.py" "$RemoteDir\app\main.py"
Upload-File "$localRoot\app\sync.py" "$RemoteDir\app\sync.py"
Upload-File "$localRoot\app\imap_client.py" "$RemoteDir\app\imap_client.py"
Upload-File "$localRoot\app\smtp_client.py" "$RemoteDir\app\smtp_client.py"
Upload-File "$localRoot\app\auth.py" "$RemoteDir\app\auth.py"
Upload-File "$localRoot\app\crypto.py" "$RemoteDir\app\crypto.py"
Upload-File "$localRoot\app\config.py" "$RemoteDir\app\config.py"
Upload-File "$localRoot\app\db.py" "$RemoteDir\app\db.py"
Upload-File "$localRoot\app\filters.py" "$RemoteDir\app\filters.py"
Upload-File "$localRoot\app\signature.py" "$RemoteDir\app\signature.py"
Upload-File "$localRoot\static\index.html" "$RemoteDir\static\index.html"
Upload-File "$localRoot\static\app.js" "$RemoteDir\static\app.js"
Upload-File "$localRoot\static\style.css" "$RemoteDir\static\style.css"
Upload-File "$localRoot\static\engrane.png" "$RemoteDir\static\engrane.png"
Upload-File "$localRoot\migrations_mysql\0001_schema.sql" "$RemoteDir\migrations_mysql\0001_schema.sql"
Upload-File "$localRoot\migrations_mysql\0002_folders_case_sensitive.sql" "$RemoteDir\migrations_mysql\0002_folders_case_sensitive.sql"
Upload-File "$localRoot\migrations_mysql\0003_account_colors.sql" "$RemoteDir\migrations_mysql\0003_account_colors.sql"
Upload-File "$localRoot\migrations_mysql\0004_pending_ops.sql" "$RemoteDir\migrations_mysql\0004_pending_ops.sql"
Upload-File "$localRoot\requirements.txt" "$RemoteDir\requirements.txt"
Upload-File "$localRoot\Dockerfile" "$RemoteDir\Dockerfile"
Upload-File "$localRoot\apply_migrations.py" "$RemoteDir\apply_migrations.py"

Write-Host "==> 3/6 Build de imagen"
Invoke-Remote "cd /d $RemoteDir && docker build -t ${ImageName}:latest ."

Write-Host "==> 4/6 Deteniendo contenedor anterior (si existe)"
Invoke-Remote "docker rm -f $ContainerName"

Write-Host "==> 5/6 Arrancando contenedor"
Invoke-Remote "docker run -d --name $ContainerName --restart unless-stopped -p 8502:8502 -v hubmail_data:/data -e HUBMAIL_DB_NAME=$DbName -e HUBMAIL_DB_SERVER=$DbServer -e HUBMAIL_DB_USER=$DbUser -e HUBMAIL_DB_PASSWORD=$DbPassword -e HUBMAIL_USERS_DB_NAME=$UsersDbName -e HUBMAIL_USERS_DB_SERVER=$UsersDbServer ${ImageName}:latest"

Write-Host "==> 6/6 Logs iniciales"
Invoke-Remote "docker logs --tail 30 $ContainerName"

Write-Host "Despliegue completado: http://172.26.90.159:8502"