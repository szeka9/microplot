import "./utils.js";

let wsWidth = 100;
let wsHeight = 100;
let wsOffsetX = 15;
let wsOffsetY = 15;
let sendInProgress = false;

let canvas;
let ctx;
let rect;
let resolutionInput;
let sketchpadOutput;
const ongoingTouches = [];
const lines = new Map();


function convertToGcode() {
    sketchpadOutput.value = "G90\n";
    lines.forEach((coordinates, lineId) => {
        let wsCoordinate = fitToWorkspace(coordinates[0], coordinates[1], canvas.width, canvas.height, wsWidth, wsHeight, wsOffsetX, wsOffsetY);
        sketchpadOutput.value += `G0 X${wsCoordinate["x"].toFixed(3)} Y${wsCoordinate["y"].toFixed(3)}\n`;
        for (let i = 2; i < coordinates.length; i += 2) {
            wsCoordinate = fitToWorkspace(coordinates[i], coordinates[i + 1], canvas.width, canvas.height, wsWidth, wsHeight, wsOffsetX, wsOffsetY);
            sketchpadOutput.value += `G1 X${wsCoordinate["x"].toFixed(3)} Y${wsCoordinate["y"].toFixed(3)}\n`;
        }
    });
    sketchpadOutput.value += "M104\n";
}


async function sendCommands() {
    const commands = document.getElementById('sketchpad-output').value.split("\n");
    if (!commands.length) {
        return;
    }

    if (sendInProgress) {
        alert("Drawing already in progress!");
        return;
    }

    document.getElementById("status-text").innerText = "sending";
    let currentQueueSize = await getQueueSize();
    sendInProgress = true;

    try {
        while (commands.length) {
            currentQueueSize = await getQueueSize();
            while (currentQueueSize > 80) {
                await new Promise(r => setTimeout(r, 5000));
                console.log(`current queue size: ${currentQueueSize}`);
                currentQueueSize = await getQueueSize();
            }
            const commandsToSend = commands.splice(0, 5);
            const gcodeRequest = new Request('/plotter/gcode',
                {
                    method: 'POST',
                    body: commandsToSend.join("\n")
                }
            );
            console.log(commandsToSend.join("\n"));
            fetch(gcodeRequest);
            await new Promise(r => setTimeout(r, 500));
        }
        let statusText = document.getElementById("status-text");
        if (statusText) {
            statusText.innerText = "drawing";
        }
        while (await getQueueSize() > 0) {
            await new Promise(r => setTimeout(r, 5000));
        }
    }
    finally {
        let statusText = document.getElementById("status-text");
        if (statusText) {
            statusText.innerText = "idle";
        }
        sendInProgress = false;
    }
}


function normalizeTouchEvent(e) {
    e.normalizedTouches = Array.from(e.changedTouches).map(touch => ({
        x: touch.clientX - rect.left,
        y: touch.clientY - rect.top,
        identifier: touch.identifier
    }));
    if (e.normalizedTouches.length > 0) {
        e.x = e.normalizedTouches[0].x;
        e.y = e.normalizedTouches[0].y;
    }
    return e;
}


function handleStart(evt) {
    evt.preventDefault();
    const touches = evt.normalizedTouches;

    for (let i = 0; i < touches.length; i++) {
        const touch = touches[i];
        ongoingTouches.push(copyTouch(touch));
        ctx.beginPath();
        ctx.arc(touch.x, touch.y, 4, 0, 2 * Math.PI, false);
        ctx.fillStyle = 'black';
        ctx.fill();

        lines.set(touch.identifier, []);
        lines.get(touch.identifier).push(touch.x);
        lines.get(touch.identifier).push(touch.y);
    }
}


function handleEnd(evt) {
    evt.preventDefault();
    const touches = evt.normalizedTouches;
    for (const touch of touches) {
        let idx = ongoingTouchIndexById(touch.identifier);

        if (idx >= 0) {
            ctx.lineWidth = 2;
            ctx.fillStyle = 'black';
            ctx.beginPath();
            ctx.moveTo(ongoingTouches[idx].x, ongoingTouches[idx].y);
            ctx.lineTo(touch.x, touch.y);
            ctx.fillRect(touch.x - 4, touch.y - 4, 8, 8);
            ongoingTouches.splice(idx, 1);
        }
        lines.get(touch.identifier).push(touch.x);
        lines.get(touch.identifier).push(touch.y);

        for (let i = 0; i < lines.get(touch.identifier).length; i += 2) {
            const px = lines.get(touch.identifier)[i];
            const py = lines.get(touch.identifier)[i + 1];
            ctx.fillStyle = "red";
            ctx.fillRect(px - 2.5, py - 2.5, 5, 5);
        }
        lines.set(Date.now(), lines.get(touch.identifier));
        lines.delete(touch.identifier);
    }
    convertToGcode();
}


function handleCancel(evt) {
    evt.preventDefault();
    const touches = evt.normalizedTouches;

    for (const touch of touches) {
        let idx = ongoingTouchIndexById(touch.identifier);
        ongoingTouches.splice(idx, 1);
    }
}


function handleMove(evt) {
    evt.preventDefault();
    const touches = evt.normalizedTouches;

    for (const touch of touches) {
        const idx = ongoingTouchIndexById(touch.identifier);

        if (idx >= 0) {
            ctx.beginPath();
            ctx.moveTo(ongoingTouches[idx].x, ongoingTouches[idx].y);
            ctx.lineTo(touch.x, touch.y);
            ctx.lineWidth = 2;
            ctx.strokeStyle = 'black';
            ctx.stroke();

            ongoingTouches.splice(idx, 1, copyTouch(touch));
        }
        const num_coordinates = lines.get(touch.identifier).length;
        const prev_x = lines.get(touch.identifier)[num_coordinates - 2];
        const prev_y = lines.get(touch.identifier)[num_coordinates - 1];
        const distance = Math.sqrt(Math.pow(touch.x - prev_x, 2) + Math.pow(touch.y - prev_y, 2));

        if (distance > resolutionInput.value) {
            lines.get(touch.identifier).push(touch.x);
            lines.get(touch.identifier).push(touch.y);
        }
    }
}


function copyTouch({ identifier, x, y }) {
    return { identifier, x, y };
}


function ongoingTouchIndexById(idToFind) {
    for (let i = 0; i < ongoingTouches.length; i++) {
        const id = ongoingTouches[i].identifier;

        if (id === idToFind) {
            return i;
        }
    }
    return -1;
}


function resetCanvas() {
    ctx.reset();
    lines.clear();
    sketchpadOutput.value = "";
}


let touchStartEventHandler = null;
let touchEndEventHandler = null;
let touchCancelEventHandler = null;
let touchMoveEventHandler = null;

let tilingSetupEventHandler = null;
let canvasResetEventHandler = null;
let machineTilingeventHandler = null;
let closePreviewEventHandler = null;

let tilingSizeInputEventHandler = null;

export function main() {
    // Global variables
    resolutionInput = document.getElementById("resolution-input");
    sketchpadOutput = document.getElementById("sketchpad-output");

    canvas = document.getElementById("canvas");
    ctx = canvas.getContext("2d");
    rect = canvas.getBoundingClientRect();

    // Touch events
    touchStartEventHandler = e => {
        if (!sendInProgress) {
            e = normalizeTouchEvent(e);
            handleStart(e);
        }
    };
    canvas.addEventListener("touchstart", touchStartEventHandler);

    touchEndEventHandler = e => {
        if (!sendInProgress) {
            e = normalizeTouchEvent(e);
            handleEnd(e);
        }
    };
    canvas.addEventListener("touchend", touchEndEventHandler);

    touchCancelEventHandler = e => {
        if (!sendInProgress) {
            e = normalizeTouchEvent(e);
            handleCancel(e);
        }
    };
    canvas.addEventListener("touchcancel", touchCancelEventHandler);

    touchMoveEventHandler = e => {
        if (!sendInProgress) {
            e = normalizeTouchEvent(e);
            handleMove(e);
        }
    };
    canvas.addEventListener("touchmove", touchMoveEventHandler);

    // Buttons
    const tilingSetupBtn = document.getElementById("tiling-setup");
    const canvasResetBtn = document.getElementById("canvas-reset");
    const machineTilingBtn = document.getElementById("machine-tiling");
    const closePreviewBtn = document.getElementById("close-preview");

    // Button events
    tilingSetupEventHandler = () => {
        setupTiling();
    };
    tilingSetupBtn.addEventListener("click", tilingSetupEventHandler);

    canvasResetEventHandler = () => {
        resetCanvas();
    };
    canvasResetBtn.addEventListener("click", canvasResetEventHandler);

    machineTilingeventHandler = () => {
        setMachineTiling();
        sendCommands();
    };
    machineTilingBtn.addEventListener("click", machineTilingeventHandler);

    closePreviewEventHandler = () => {
        hideTilingPreview();
    };
    closePreviewBtn.addEventListener("click", closePreviewEventHandler);

    // Tiling
    let tilingSizeInput = document.getElementById("tiling-size");

    tilingSizeInputEventHandler = () => {
        updateTiles();
    };
    tilingSizeInput.addEventListener("input", tilingSizeInputEventHandler);
}


export function cleanup() {
    canvas.removeEventListener("touchstart", touchStartEventHandler);
    canvas.removeEventListener("touchend", touchEndEventHandler);
    canvas.removeEventListener("touchcancel", touchCancelEventHandler);
    canvas.removeEventListener("touchmove", touchMoveEventHandler);
    touchStartEventHandler = null;
    touchEndEventHandler = null;
    touchCancelEventHandler = null;
    touchMoveEventHandler = null;

    const tilingSetupBtn = document.getElementById("tiling-setup");
    const canvasResetBtn = document.getElementById("canvas-reset");
    const machineTilingBtn = document.getElementById("machine-tiling");
    const closePreviewBtn = document.getElementById("close-preview");

    tilingSetupBtn.removeEventListener("click", tilingSetupEventHandler);
    canvasResetBtn.removeEventListener("click", canvasResetEventHandler);
    machineTilingBtn.removeEventListener("click", machineTilingeventHandler);
    closePreviewBtn.removeEventListener("click", closePreviewEventHandler);
    tilingSetupEventHandler = null;
    canvasResetEventHandler = null;
    machineTilingeventHandler = null;
    closePreviewEventHandler = null;

    let tilingSizeInput = document.getElementById("tiling-size");
    tilingSizeInput.removeEventListener("input", tilingSizeInputEventHandler);
    tilingSizeInputEventHandler = null;
}
