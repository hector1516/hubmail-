param(
    [string]$RemoteDir = "C:/Users/eccsa/hubmail",
    [string]$ImageName = "eccsa/hubmail",
    [string]$ContainerName = "hubmail",
    [string]$DbName = "ECCSA_Admon_Pruebas",
    [string]$DbServer = "172.26.117.220"
)

$plink = "C:\Users\hecto\AppData\Local\Temp\opencode\plink.exe"
$pscp = "C:\Users\hecto\AppData\Local\Temp\opencode\pscp.exe"
$hostkey = "SHA256:QClufJSyrTFwVoHmdc1hZTT8k3A/cWYiXMUKICF1iTc"
$user = "eccsa@172.26.90.159"
$pw = "eyccazo"
$localRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Invoke-Remote([string]$cmd) {
    & $plink -batch -ssh $user -pw $pw -hostkey $hostkey $cmd
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR remoto (exit $LASTEXITCODE): $cmd" -ForegroundColor Red; exit 1 }
}

Write-Host "==> 1/5 Creando directorio remoto"
& $plink -batch -ssh $user -pw $pw -hostkey $hostkey "mkdir C:\Users\eccsa\hubmail" 2>&1 | Out-Null

Write-Host "==> 2/5 Subiendo codigo"
& $pscp -batch -scp -pw $pw -hostkey $hostkey -r "$localRoot\app" "$localRoot\static" "$localRoot\migrations" "$localRoot\requirements.txt" "$localRoot\Dockerfile" "$localRoot\apply_migrations.py" "${user}:${RemoteDir}/"
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR al subir archivos" -ForegroundColor Red; exit 1 }

Write-Host "==> 3/5 Build de imagen"
Invoke-Remote "cd /d C:\Users\eccsa\hubmail && docker build -t ${ImageName}:latest ."

Write-Host "==> 4/5 Deteniendo contenedor anterior (si existe)"
Invoke-Remote "docker rm -f $ContainerName"

Write-Host "==> 5/5 Arrancando contenedor"
Invoke-Remote "docker run -d --name $ContainerName --restart unless-stopped -p 8502:8502 -v hubmail_data:/data -e HUBMAIL_DB_NAME=$DbName -e HUBMAIL_DB_SERVER=$DbServer ${ImageName}:latest"

Write-Host "==> Logs iniciales"
Invoke-Remote "docker logs --tail 30 $ContainerName"

Write-Host "Despliegue completado: http://172.26.90.159:8502"