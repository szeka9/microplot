import "./utils.js";

var commandPointer = 0;
var penRaised = true;
var paused = false;
const commandHistory = [];


function getStatus() {
    const statusRequest = new Request('/plotter/status',
        {
            method: 'GET'
        }
    );
    fetch(statusRequest)
        .then((response) => {
            if (!response.ok) {
                throw new Error(`Could not get machine status, ${response.status}`);
            }
            return response.json();
        })
        .then((json) => {
            document.getElementById('coordinate-system').innerText = json['coordinate_system'];
            document.getElementById('x-status').innerText = json['x'];
            document.getElementById('y-status').innerText = json['y'];
            document.getElementById('mode-status').innerText = json['positioning'];
            document.getElementById('active-status').innerText = json['active'];
            document.getElementById('queue-status').innerText = json['queue_size'];
            document.getElementById('paused-status').innerText = json['paused'];
            document.getElementById('limit-status').innerText = json['limit_primary'] || json['limit_secondary'];
            document.getElementById('event-history').value = json['additional_info'].join('\n\n');
        })
        .catch((error) => {
            document.getElementById('plotter-status').innerText = `Error: ${error.message}`;
        })

}


function togglePuase() {
    paused = !paused;
    let pauseButton = document.getElementById('pause-button');
    if (paused) {
        pauseButton.innerText = "Continue";
    } else {
        pauseButton.innerText = "Pause";
    }

    const pauseRequest = new Request('/plotter/pause',
        {
            method: 'POST',
            body: paused
        }
    );
    fetch(pauseRequest);
}


function stopMachine() {
    const stopRequest = new Request('/plotter/stop',
        {
            method: 'POST'
        }
    );
    fetch(stopRequest);
}


function testRoutine() {
    const testRequest = new Request('/plotter/test',
        {
            method: 'POST'
        }
    );
    fetch(testRequest);
}


function buttonInstruction(xRel, yRel, flipPen = false) {
    let movementMode = '';
    if (flipPen) {
        penRaised = !penRaised;
        if (penRaised) {
            document.getElementById('pen-flip').innerHTML = '&#9678';
        } else {
            document.getElementById('pen-flip').innerHTML = '&#9673';
        }
    }

    if (penRaised) {
        movementMode = 'G0';
    } else {
        movementMode = 'G1';
    }

    let stepIncrement = document.getElementById('step-slider').value;

    const command = 'G91' + ' ' +
        movementMode + ' ' +
        'X' + xRel * stepIncrement + ' ' +
        'Y' + yRel * stepIncrement;

    sendCommand(command);
}


function sendCommand(command = "") {
    commandPointer = 0;
    if (!command) {
        const commandSender = document.getElementById('command-sender');
        command = commandSender.value;
        if (command) {
            commandSender.value = '';
        }
    }

    if (!command) {
        return;
    }

    const commandHistoryOutput = document.getElementById('command-history');
    if (command.toLocaleLowerCase() == "help") {
        commandHistoryOutput.value = getCommandsDescription().split('\n').map(e => e.trim()).join('\n');
        return;
    } else if (command == "M06" || command == "M6") {
        paused = true;
        let pauseButton = document.getElementById('pause-button');
        pauseButton.innerText = "Continue";
    }

    const gcodeRequest = new Request('/plotter/gcode',
        {
            method: 'POST',
            body: command
        }
    );
    fetch(gcodeRequest);

    const instructionCount = commandHistory.length;
    commandHistory.push(instructionCount + ': ' + command);
    commandHistoryOutput.value = commandHistory.join('\n');
    commandHistoryOutput.scrollTop = commandHistoryOutput.scrollHeight;
}


function stagePreviousCommand() {
    if (commandPointer < commandHistory.length) {
        commandPointer += 1;
        const lastCommand = commandHistory[commandHistory.length - commandPointer];
        const commandSender = document.getElementById('command-sender');
        commandSender.value = lastCommand.split(':')[1].trim();
    }
}


function stageEarlierCommand() {
    const commandSender = document.getElementById('command-sender');
    if (commandPointer > 1) {
        commandPointer -= 1;
        const lastCommand = commandHistory[commandHistory.length - commandPointer];
        commandSender.value = lastCommand.split(':')[1].trim();
    } else if (commandPointer == 1) {
        commandPointer -= 1;
        commandSender.value = "";
    }
}

let keyDownEventListener = null;
let inputEventListener = null;

let pauseButtonEventListener = null;
let stopButtonEventListener = null;
let testButtonEventListener = null;
let workspaceButtonEventListener = null;
let stepLossButtonEventListener = null;
let feedratesButtonEventListener = null;

let upLeftButtonEventListener = null;
let upButtonEventListener = null;
let upRightButtonEventListener = null;
let leftButtonEventListener = null;
let penFlipButtonEventListener = null;
let rightButtonEventListener = null;
let downLeftButtonEventListener = null;
let downButtonEventListener = null;
let downRightButtonEventListener = null;
let sendCommandButtonEventListener = null;

let statusInterval = null;

export function main() {
    getStatus();
    statusInterval = setInterval(function () {
        getStatus();
    }, 5000);

    keyDownEventListener = (event) => {
        if (event.key === "Enter") {
            sendCommand();
        }
        if (event.key === "ArrowUp") {
            stagePreviousCommand();
        }
        if (event.key === "ArrowDown") {
            stageEarlierCommand();
        }
    };
    document.getElementById("command-sender").addEventListener("keydown", keyDownEventListener);

    inputEventListener = (event) => {
        const stepSliderOutput = document.getElementById("step-slider-value");
        stepSliderOutput.innerText = event.target.value + "mm";
    };
    document.getElementById("step-slider").addEventListener("input", inputEventListener);

    window.togglePuase = togglePuase;
    window.stopMachine = stopMachine;
    window.testRoutine = testRoutine;
    window.buttonInstruction = buttonInstruction;
    window.sendCommand = sendCommand;

    // Buttons
    const pauseButton = document.getElementById("pause-button");
    const stopButton = document.getElementById("stop-button");
    const testButton = document.getElementById("test-button");
    const workspaceButton = document.getElementById("workspace-button");
    const stepLossButton = document.getElementById("step-loss-button");
    const feedratesButton = document.getElementById("feedrates-button");

    const upLeftButton = document.getElementById("up-left-button");
    const upButton = document.getElementById("up-button");
    const upRightButton = document.getElementById("up-right-button");
    const leftButton = document.getElementById("left-button");
    const penFlipButton = document.getElementById("pen-flip");
    const rightButton = document.getElementById("right-button");
    const downLeftButton = document.getElementById("down-left-button");
    const downButton = document.getElementById("down-button");
    const downRightButton = document.getElementById("down-right-button");
    const sendCommandButton = document.getElementById("send-command-button");


    // Button events
    pauseButtonEventListener = () => { togglePuase(); };
    pauseButton.addEventListener("click", pauseButtonEventListener);
    stopButtonEventListener = () => { stopMachine(); };
    stopButton.addEventListener("click", stopButtonEventListener);
    testButtonEventListener = () => { testRoutine(); };
    testButton.addEventListener("click", testButtonEventListener);
    workspaceButtonEventListener = () => { sendCommand('M100'); };
    workspaceButton.addEventListener("click", workspaceButtonEventListener);
    stepLossButtonEventListener = () => { sendCommand('M101'); };
    stepLossButton.addEventListener("click", stepLossButtonEventListener);
    feedratesButtonEventListener = () => { sendCommand('M102'); };
    feedratesButton.addEventListener("click", feedratesButtonEventListener);

    upLeftButtonEventListener = () => { buttonInstruction(-1, 1); };
    upLeftButton.addEventListener("click", upLeftButtonEventListener);
    upButtonEventListener = () => { buttonInstruction(0, 1); };
    upButton.addEventListener("click", upButtonEventListener);
    upRightButtonEventListener = () => { buttonInstruction(1, 1); };
    upRightButton.addEventListener("click", upRightButtonEventListener);
    leftButtonEventListener = () => { buttonInstruction(-1, 0); };
    leftButton.addEventListener("click", leftButtonEventListener);
    penFlipButtonEventListener = () => { buttonInstruction(0, 0, true); };
    penFlipButton.addEventListener("click", penFlipButtonEventListener);
    rightButtonEventListener = () => { buttonInstruction(1, 0); };
    rightButton.addEventListener("click", rightButtonEventListener);
    downLeftButtonEventListener = () => { buttonInstruction(-1, -1); };
    downLeftButton.addEventListener("click", downLeftButtonEventListener);
    downButtonEventListener = () => { buttonInstruction(0, -1); };
    downButton.addEventListener("click", downButtonEventListener);
    downRightButtonEventListener = () => { buttonInstruction(1, -1); };
    downRightButton.addEventListener("click", downRightButtonEventListener);
    sendCommandButtonEventListener = () => { sendCommand(); };
    sendCommandButton.addEventListener("click", sendCommandButtonEventListener);
}

export function cleanup() {
    document.getElementById("command-sender").removeEventListener("keydown", keyDownEventListener);
    keyDownEventListener = null;

    document.getElementById("step-slider").removeEventListener("input", inputEventListener);
    inputEventListener = null;

    const pauseButton = document.getElementById("pause-button");
    const stopButton = document.getElementById("stop-button");
    const testButton = document.getElementById("test-button");
    const workspaceButton = document.getElementById("workspace-button");
    const stepLossButton = document.getElementById("step-loss-button");
    const feedratesButton = document.getElementById("feedrates-button");

    const upLeftButton = document.getElementById("up-left-button");
    const upButton = document.getElementById("up-button");
    const upRightButton = document.getElementById("up-right-button");
    const leftButton = document.getElementById("left-button");
    const penFlipButton = document.getElementById("pen-flip");
    const rightButton = document.getElementById("right-button");
    const downLeftButton = document.getElementById("down-left-button");
    const downButton = document.getElementById("down-button");
    const downRightButton = document.getElementById("down-right-button");
    const sendCommandButton = document.getElementById("send-command-button");

    pauseButton.removeEventListener("click", pauseButtonEventListener);
    pauseButtonEventListener = null;
    stopButton.removeEventListener("click", stopButtonEventListener);
    stopButtonEventListener = null;
    testButton.removeEventListener("click", testButtonEventListener);
    testButtonEventListener = null;
    workspaceButton.removeEventListener("click", workspaceButtonEventListener);
    workspaceButtonEventListener = null;
    stepLossButton.removeEventListener("click", stepLossButtonEventListener);
    stepLossButtonEventListener = null;
    feedratesButton.removeEventListener("click", feedratesButtonEventListener);
    feedratesButtonEventListener = null;

    upLeftButton.removeEventListener("click", upLeftButtonEventListener);
    upLeftButtonEventListener = null;
    upButton.removeEventListener("click", upButtonEventListener);
    upButtonEventListener = null;
    upRightButton.removeEventListener("click", upRightButtonEventListener);
    upRightButtonEventListener = null;
    leftButton.removeEventListener("click", leftButtonEventListener);
    leftButtonEventListener = null;
    penFlipButton.removeEventListener("click", penFlipButtonEventListener);
    penFlipButtonEventListener = null;
    rightButton.removeEventListener("click", rightButtonEventListener);
    rightButtonEventListener = null;
    downLeftButton.removeEventListener("click", downLeftButtonEventListener);
    downLeftButtonEventListener = null;
    downButton.removeEventListener("click", downButtonEventListener);
    downButtonEventListener = null;
    downRightButton.removeEventListener("click", downRightButtonEventListener);
    downRightButtonEventListener = null;
    sendCommandButton.removeEventListener("click", sendCommandButtonEventListener);
    sendCommandButtonEventListener = null;

    clearInterval(statusInterval);
}
