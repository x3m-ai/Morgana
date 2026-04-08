# Morgana NT Service Setup

## Obiettivo

Installare Morgana come **Windows NT Service** che:
- Si avvia automaticamente al boot
- Gira sotto l'account **LocalSystem** (nessuna password)
- Logga su file (`server/logs/service.log`) e su Event Viewer (source = nssm)
- Si riavvia automaticamente in caso di crash

---

## Il problema attuale

**Python MS Store** (`WindowsApps/PythonSoftwareFoundation.Python.3.11`) usa file
reparse di tipo AppExecLink che funzionano SOLO in una sessione utente interattiva.
Il service account `LocalSystem` non puo risolverli -> il processo Python esce
immediatamente con **exit code 101**.

Il server funziona perfettamente come processo normale (utente interattivo),
ma crasha appena viene avviato da SCM/NSSM come servizio.

---

## La soluzione

Usare **Python.org Python 3.11** (non MS Store) per il venv di Morgana.
Il Python.org installa in `C:\Python311\` ed e un normale eseguibile PE32
che LocalSystem puo lanciare senza problemi.

---

## Passi da eseguire (una tantum)

### 1. Installa Python.org 3.11

Da un terminale **elevato (Administrator)**:

```powershell
winget install Python.Python.3.11
```

Verifica che sia installato in `C:\Python311\`:

```powershell
C:\Python311\python.exe --version
```

### 2. Ricrea il venv con Python.org

```powershell
cd C:\Users\ninoc\OfficeAddinApps\Morgana\server
Remove-Item .venv -Recurse -Force
C:\Python311\python.exe -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

### 3. Verifica che il venv ora usi Python.org

```powershell
Get-Content .venv\pyvenv.cfg
# La riga "home = ..." deve puntare a C:\Python311, NON a WindowsApps
```

### 4. Installa il servizio

```powershell
cd C:\Users\ninoc\OfficeAddinApps\Morgana
.\Morgana.ps1 install -LogLevel INFO -AutoStart
```

### 5. Avvia e verifica

```powershell
.\Morgana.ps1 start
.\Morgana.ps1 status
Start-Sleep 15
Invoke-WebRequest http://localhost:8888/ui/ -UseBasicParsing | Select-Object StatusCode
```

---

## Comportamento di Morgana.ps1 dopo il fix

| Scenario | Comportamento |
|----------|--------------|
| venv usa Python.org | Installa servizio come LocalSystem, nessuna password |
| venv usa MS Store Python | Si ferma con errore + istruzioni per il fix |

---

## Infrastruttura

| Componente | Percorso |
|-----------|---------|
| Script manager | `Morgana.ps1` |
| NSSM | `tools\nssm.exe` (v2.24 win64) |
| Server | `server\main.py` (FastAPI, porta 8888) |
| venv Python (dopo fix) | `server\.venv\Scripts\python.exe` -> `C:\Python311\` |
| Log stdout | `server\logs\service.log` |
| Log stderr | `server\logs\service_error.log` |
| Event Viewer | Windows Logs -> Application -> Source = nssm |

---

## Comandi di gestione servizio

```powershell
.\Morgana.ps1 install -LogLevel INFO -AutoStart   # installa (una tantum)
.\Morgana.ps1 start                                # avvia
.\Morgana.ps1 stop                                 # ferma
.\Morgana.ps1 restart                              # riavvia
.\Morgana.ps1 status                               # stato corrente
.\Morgana.ps1 uninstall                            # rimuove
```
