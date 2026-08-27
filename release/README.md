# Releases versionados de la estación de pesaje

Este directorio implementa el carril de actualización del módulo edge. El código se instala en versiones paralelas y la información de planta permanece fuera del release.

## Contrato operativo

- Código inmutable: `C:\Program Files\EnvaPeru\Pesaje\releases\{version}`.
- Datos, token DPAPI, configuración, logs y backups: `C:\ProgramData\EnvaPeru\Pesaje`.
- Puntero activo: `ProgramData\run\active-release.json`.
- Una actualización nunca elimina un release previo.
- Antes de activar se verifica el SHA-256 del ZIP, cada archivo del manifiesto, un backup SQLite y una migración sobre una copia.
- La estación se detiene solo después del preflight. Si el nuevo runtime no llega a `READY`, se restaura el puntero, la base previa y el runtime anterior.
- No se actualiza durante un pesaje, una impresión pendiente ni una sesión operativa activa.

El SHA-256 prueba integridad. Para el piloto, la autoridad del paquete proviene del artefacto privado generado por CI y del valor comunicado por soporte por un canal separado. La firma de código Authenticode queda como gate antes de distribuir releases fuera de ese canal controlado.

## Crear un paquete

```powershell
.\release\Build-StationRelease.ps1 -Version 1.2.0
```

El resultado contiene el ZIP y su `.sha256`. El frontend ya está compilado y el directorio `wheels` permite instalar Python sin Internet ni Node.js en la PC de planta.

## Actualizar una estación

Ejecutar PowerShell como administrador, fuera del horario de pesaje:

```powershell
.\release\Update-Station.ps1 `
  -PackagePath C:\Soporte\envaperu-pesaje-1.2.0-win-x64.zip `
  -ExpectedSha256 <sha256-comunicado-por-soporte>
```

La salida terminal válida es `UPDATE_COMPLETE`. `UPDATE_STAGED` solo se usa en pruebas o cuando soporte difiere conscientemente el arranque.

Después de la primera instalación versionada, registrar una vez el launcher estable al iniciar sesión:

```powershell
C:\Program Files\EnvaPeru\Pesaje\launcher\Install-StationTask.ps1
```

La tarea no apunta a una versión concreta. En cada inicio lee `active-release.json`, evita una segunda instancia y permite que la versión cambie sin editar accesos directos.

## Rollback manual

El actualizador ya hace rollback automático si falla readiness. El rollback manual exige confirmar que no hubo nuevas capturas desde la actualización:

```powershell
.\release\Rollback-Station.ps1 -ConfirmNoCapturesSinceUpdate
```

Si hubo pesajes, impresiones o movimientos nuevos, no se ejecuta rollback ciego: se detiene la operación y se concilian primero los registros.

## Qué no hace

- no descarga ni instala una versión silenciosamente;
- no permite a Central abrir la balanza, imprimir o detener la estación;
- no borra datos de `ProgramData`;
- no sustituye el smoke físico de balanza e impresora;
- no firma todavía el paquete con un certificado Authenticode.
