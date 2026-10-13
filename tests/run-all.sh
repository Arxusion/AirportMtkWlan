#!/bin/sh
# Run every host test (they extract real driver functions and compile them
# against stubs with clang++ / ASan / UBSan). Exits non-zero on any failure.
cd "$(dirname "$0")/.." || exit 1
fail=0
for t in tests/*/*.py; do
	if python3 "$t" >/tmp/simplemtk-test.log 2>&1; then
		echo "PASS $t"
	else
		echo "FAIL $t"; cat /tmp/simplemtk-test.log; fail=1
	fi
done
if sh tests/scan/run.sh >/tmp/simplemtk-test.log 2>&1; then
	echo "PASS tests/scan/run.sh"
else
	echo "FAIL tests/scan/run.sh"; cat /tmp/simplemtk-test.log; fail=1
fi
rm -f tests/scan/scan.cpp tests/scan/scan-test /tmp/simplemtk-test.log
exit $fail
