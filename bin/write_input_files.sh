#!/bin/bash
# Get values from a .ini file
function iniget() {
    if [[ $# -lt 2 || ! -f $1 ]]; then
        echo "usage: iniget <file> [--list|<section> [key]]"
        return 1
    fi
    local inifile=$1

    if [ "$2" == "--list" ]; then
        for section in $(cat $inifile | grep "^\\s*\[" | sed -e "s#\[##g" | sed -e "s#\]##g"); do
            echo $section
        done
        return 0
    fi

    local section=$2
    local key
    [ $# -eq 3 ] && key=$3

    # This awk line turns ini sections => [section-name]key=value
    local lines=$(awk '/\[/{prefix=$0; next} $1{print prefix $0}' $inifile)
    lines=$(echo "$lines" | sed -e 's/[[:blank:]]*=[[:blank:]]*/=/g')
    while read -r line ; do
        if [[ "$line" = \[$section\]* ]]; then
            local keyval=$(echo "$line" | sed -e "s/^\[$section\]//")
            if [[ -z "$key" ]]; then
                echo $keyval
            else
                if [[ "$keyval" = $key=* ]]; then
                    echo $(echo $keyval | sed -e "s/^$key=//")
                fi
            fi
        fi
    done <<<"$lines"
}

TOP_DIR=$(pwd)
CFG_FILE="$TOP_DIR/inputs/simulation.ini"

# parse ini file
Z=$(iniget $CFG_FILE simulation z)
A=$(iniget $CFG_FILE simulation a)
G1=$(iniget $CFG_FILE simulation g1)
G2=$(iniget $CFG_FILE simulation g2)

if [[ $# != 0 ]]; then
    echo "usage: write_intput_files"
    exit 1
else
    echo "Writing input files ... "
    $TOP_DIR/bin/write_input_files.py -z $Z -a $A -g1 $G1 -g2 $G2
fi
