# micrOS Application: microplot (under development)
A small G-code interpreter and plotter application written in MicroPython, integrated with [BxNxM/micrOS](https://github.com/BxNxM/micrOS). micrOS needs to be installed before using this package.


## Installation
Install the current development version through micrOS shell CLI:
```shell
pacman install "github:szeka9/microplot"
```

Uninstall:
```shell
pacman uninstall "microplot"
```

Everything will be installed under `/lib/microplot/*` and `/modules/LM_*`

## Usage

### **load** function - load the app into memory

```commandline
microplot load "/path/to/configuration.json"
```
See example configurations under the [config](https://github.com/szeka9/microplot/tree/main/config) directory.

## MicroPython Docs `package.json` structure and `mip`

[packages](https://docs.micropython.org/en/latest/reference/packages.html)

## micrOS Project

[Project Docs](https://github.com/BxNxM/micrOS/tree/master)

[Coding Docs](https://github.com/BxNxM/micrOS/blob/master/APPLICATION_GUIDE.md)