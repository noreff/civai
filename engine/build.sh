#!/bin/bash
# Build CvGameCoreDLL.dll with MSVC 7.1 under CrossOver wine.
#   ./build.sh <source dir> <output dir> [jobs]
# Flags follow the "Final Release" configuration of CvGameCoreDLL.vcproj.
set -e
SRC="$(cd "$1" && pwd)"
OUT="$(mkdir -p "$2" && cd "$2" && pwd)"
JOBS="${3:-8}"
source "$HOME/civai-sdk/tools/vcenv.sh"
win() { echo "Z:${1//\//\\}"; }
W="$CX/wine --bottle $CX_BOTTLE --no-gui"
CL="$VCBIN\\cl.exe"
FLAGS="/nologo /c /O2 /Og /Oi /Oy /G7 /EHsc /MD /GS- /Gy /GR /W3 /D WIN32 /D NDEBUG /D _WINDOWS /D _USRDLL /D CVGAMECOREDLL_EXPORTS /D FINAL_RELEASE"
INC="/I$(win "$SRC/Boost-1.32.0/include") /I$(win "$SRC/Python24/include")"
PCH="$(win "$OUT/CvGameCoreDLL.pch")"
cd "$SRC"
newer_h=$(find "$SRC" -maxdepth 1 \( -name "*.h" -o -name "*.inl" \) -newer "$OUT/CvGameCoreDLL.pch" 2>/dev/null | head -1)
if [ ! -f "$OUT/CvGameCoreDLL.pch" ] || [ -n "$newer_h" ]; then
	echo "precompiled header..."
	$W "$CL" $FLAGS $INC /Yc"CvGameCoreDLL.h" /Fp"$PCH" /Fo"$(win "$OUT/_precompile.obj")" _precompile.cpp > "$OUT/pch.log" 2>&1 || { cat "$OUT/pch.log"; exit 1; }
fi
# compile changed files, several per wine process, JOBS processes at once
todo=()
for f in *.cpp; do
	case "$f" in _precompile.cpp|CvTextScreens.cpp) continue;; esac
	o="$OUT/${f%.cpp}.obj"
	if [ ! -f "$o" ] || [ "$f" -nt "$o" ] || [ "$OUT/CvGameCoreDLL.pch" -nt "$o" ]; then todo+=("$f"); fi
done
echo "compiling ${#todo[@]} files with $JOBS jobs..."
if [ ${#todo[@]} -gt 0 ]; then
	export W CL FLAGS INC PCH OBJDIR="$(win "$OUT")"
	printf "%s\n" "${todo[@]}" | xargs -P "$JOBS" -n 1 "$HOME/civai-sdk/compile_one.sh" "$OUT"
fi
echo "linking..."
( cd "$OUT" && for o in *.obj; do echo "\"$(win "$OUT/$o")\""; done ) > "$OUT/objs.rsp"
$W "$VCBIN\\link.exe" /nologo /DLL /OPT:REF /OPT:ICF /LARGEADDRESSAWARE /SUBSYSTEM:WINDOWS /MACHINE:X86 \
	/LIBPATH:"$(win "$SRC/Python24/libs")" /LIBPATH:"$(win "$SRC/Boost-1.32.0/libs")" \
	/OUT:"$(win "$OUT/CvGameCoreDLL.dll")" @"$(win "$OUT/objs.rsp")" boost_python-vc71-mt-1_32.lib winmm.lib user32.lib > "$OUT/link.log" 2>&1 || { cat "$OUT/link.log"; exit 1; }
grep -i "error\|warning LNK" "$OUT/link.log" | head -5 || true
ls -l "$OUT/CvGameCoreDLL.dll"
