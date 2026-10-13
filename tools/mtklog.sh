#!/bin/sh
# Print the SimpleMtkWlan persistent debug log from IORegistry.
echo "loaded: $(kmutil showloaded 2>/dev/null | grep -o 'com.laobamac.SimpleMtkWlan.*' )"
echo "instances: $(ioclasscount SimpleMtkWlan 2>/dev/null)"
ioreg -l -w0 -r -c IOPCIDevice | awk '/"MtkDebugLog" = "/{f=1} f{ if (n++ && /^ *"[A-Za-z-]+" = /) exit; print }'
