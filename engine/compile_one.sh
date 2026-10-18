#!/bin/bash
# compile_one.sh <out dir> <file.cpp>: one file, 5-minute limit, 3 tries (wine sometimes hangs or misreads headers)
out="$1"; f="$2"
log="$out/log_${f%.cpp}.txt"
for try in 1 2 3; do
	if perl -e 'alarm 300; exec @ARGV' $W "$CL" $FLAGS $INC /Yu"CvGameCoreDLL.h" /Fp"$PCH" /Fo"$OBJDIR\\" "$f" > "$log" 2>&1; then exit 0; fi
	echo "retry $try: $f"
done
echo "FAILED: $f"; cat "$log"; exit 255
