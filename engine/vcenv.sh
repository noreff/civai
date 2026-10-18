# source me: sets env for running MSVC 7.1 under CrossOver wine (bottle civ4sdk)
export CX="$HOME/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin"
export CX_BOTTLE=civ4sdk
export WINEDEBUG=-all
export INCLUDE='Z:\Users\volod\civai-sdk\vc71\include;Z:\Users\volod\civai-sdk\psdk\Include'
export LIB='Z:\Users\volod\civai-sdk\vc71\lib;Z:\Users\volod\civai-sdk\psdk\Lib'
export WINEPATH='Z:\Users\volod\civai-sdk\vc71\bin'
export WSLENV=INCLUDE:LIB
VCBIN='Z:\Users\volod\civai-sdk\vc71\bin'
cl()   { "$CX/wine" --bottle civ4sdk --no-gui "$VCBIN\\cl.exe" "$@"; }
vlink(){ "$CX/wine" --bottle civ4sdk --no-gui "$VCBIN\\link.exe" "$@"; }
