# Repository layout and release packaging

The plugin runtime modules, metadata and icon remain at the repository root.
This preserves relative imports and QGIS plugin loading.

| Location | Purpose |
| --- | --- |
| scripts/ | Packaging and development utilities |
| tests/ | Automated checks and QGIS integration scenarios |
| docs/ | Review reports, validation evidence and documentation |
| releases/ | Generated installers and extracted verification copies; ignored by Git |
| dist/ | Generated compatibility artifacts; ignored by Git |

## Build an installer

Current version: 1.1.0, declared in metadata.txt. From the repository root:

~~~text
python scripts/package_plugin.py --output releases/NEW_DELIVERY --extract-to releases/NEW_DELIVERY/verified
~~~

Replace NEW_DELIVERY with a new dated directory. Keep previous delivery folders
when reproducing or correcting an installer. In managed local environments,
invoke development commands through the existing DEVRESOURCES_RUN.cmd launcher.
Machine-specific launchers and resource configuration remain local.

The archive must contain exactly one top-level plugin directory named
qgis_rrim. Preserve its spelling and case: the QGIS repository matches it
against the existing plugin package. The visible plugin name is a separate
metadata field.

Check ZIP integrity, metadata version, source agreement and Python syntax.
Run the applicable automated and native QGIS checks for functional changes;
record which checks were actually executed. A packaging check alone does not
replace runtime validation.

## Publish

Publish installers and SHA-256 checksums as GitHub release assets, rather than
committing generated ZIP files or extracted packages. Preserve prior assets
before replacing an existing installer, and update its checksum and notes.
Do not move existing version tags implicitly.

GitHub release publication and QGIS Plugin Repository submission are separate.
Use Add version on the existing QGIS plugin entry and retain its registered
package directory. Reports and release notes must distinguish previous runtime
validation from checks repeated for a refreshed installer.
