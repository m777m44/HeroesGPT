"""nemo-gym resources_server for the ``tng_json_format`` env.

This directory is a self-contained nemo-gym resources_server. It is symlinked
into ``nemo-gym/resources_servers/tng_json_format`` at smoke-run time by
``scripts/smoke_json_format.sh`` so ``ng_run`` can discover it by its standard
``{server_type}/{name}`` convention. The symlink is removed on exit.

Single source of truth: this directory. The sibling nemo-gym working tree does
not carry any persistent copy of this code.
"""
