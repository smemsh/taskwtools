#
# - localized sh environment setup needed for execution of taskw/timew scripts
# - sourced by shells that need to use it, especially bashrc and wm scripts
#

# share timewarrior db dir with taskwarrior, filenames do not collide
export TIMEWARRIORDB=$HOME/.task
