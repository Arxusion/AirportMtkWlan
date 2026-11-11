#!/bin/sh
# Print the SimpleMtkWlan / AirportMtkWlan persistent debug log from IORegistry.
# For full bug-report log collection (redacted tarball), run ./tools/mtk-grab-logs.sh.
echo "loaded: $(kmutil showloaded 2>/dev/null | grep -oE "com.(laobamac.SimpleMtkWlan|flxxxxddd.AirportMtkWlan).*" )"
echo "instances: SimpleMtkWlan=$(ioclasscount SimpleMtkWlan 2>/dev/null) AirportItlwm=$(ioclasscount AirportItlwm 2>/dev/null)"
ioreg -l -w0 -r -c IOPCIDevice | awk '/"MtkDebugLog" = "/{f=1} f{ if (n++ && /^ *"[A-Za-z-]+" = /) exit; print }'
