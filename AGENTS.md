# Instrucciones del repositorio

## Recursos locales y conservacion


Antes de cambiar recursos comprueba unidades, instrucciones, remotos, ramas y cambios locales. Actualiza mediante pull con avance rapido y conserva cambios; informa divergencias sin reset ni cambio de rama.
Usa la raiz local D:\DevResources cuando sea valida; si no lo es, solicita elegir otra raiz. Reutiliza SDK y caches compatibles en Shared, separa estado mutable por proyecto y usa Sessions unicas por ejecucion.
Usa DEVRESOURCES_RUN.cmd para comandos de desarrollo; las configuraciones .devresources son locales y no deben subirse. TEMP y TMP se cambian solo para la sesion y sus hijos. Coordina bloqueos por workspace y maximo dos compilaciones pesadas.
No detengas procesos ajenos. No modifiques DriveFS, datos ni sincronizacion de Google Drive. Conserva codigo, datos, autenticacion, claves y enlaces de compatibilidad.
Comprueba rutas y lanzadores antes de consolidar. Antes de cualquier eliminacion presenta candidatos y espera autorizacion expresa; verifica referencias, copias, destinos fisicos e inactividad. No ejecutes limpiezas automaticas durante esta auditoria.
No afirmes compilaciones que no ejecutaste. Los informes Markdown y Word no deben contener backticks.
