# micrOS Application: microPlot
A small G-code interpreter and plotter application written in MicroPython, integrated with [BxNxM/micrOS](https://github.com/BxNxM/micrOS). micrOS needs to be installed before using this package.


## Installation
Install latest official package version:
```shell
pacman install "github:BxNxM/micrOSPackages/microPlot"
```

Install development versions through micrOS shell CLI:
```shell
pacman install "github:szeka9/microPlot"
```

Uninstall:
```shell
pacman uninstall "microPlot"
```

Everything will be installed under `/lib/microPlot/*` and `/modules/LM_*`


## MicroPython Docs `package.json` structure and `mip`

[packages](https://docs.micropython.org/en/latest/reference/packages.html)

## micrOS Project

[Project Docs](https://github.com/BxNxM/micrOS/tree/master)

[Coding Docs](https://github.com/BxNxM/micrOS/blob/master/APPLICATION_GUIDE.md)

## Usage

### **load** function - load the app into memory

```commandline
microplot load
```
