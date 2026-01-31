function getQueueSize() {
    const statusRequest = new Request('/plotter/status',
        {
            method: 'GET'
        }
    );
    return fetch(statusRequest)
        .then((response) => {
            if (!response.ok) {
                throw new Error(`Could not get machine status, ${response.status}`);
            }
            return response.json();
        })
        .then((json) => {
            return json['queue_size'];
        })
}


function fitToWorkspace(x, y, xMax, yMax, wsWidth, wsHeight, wsOffsetX, wsOffsetY) {
    x = Math.max(Math.min(xMax, x), 0);
    y = Math.max(Math.min(yMax, y), 0);

    return {
        x: (x / xMax) * wsWidth + wsOffsetX,
        y: wsHeight - ((y / yMax) * wsHeight) + wsOffsetY
    };
}


function getCommandsDescription() {
    return `-----Positioning------
        G28:        home cycle
        G90:        absolute pos.
        G91:        relative pos.
        G0 X1Y1:    travel to (1;1)
        G1 X1Y1:    draw to (1;1)

        ---Machine commands---
        M06:        change tool
        M100:       measure workspace
        M101:       measure step loss
        M102:       measure feedrate
        M103 X+:    unblock x limit (+)
        M103 X-:    unblock x limit (-)
        M103 Y+:    unblock y limit (+)
        M103 Y-:    unblock y limit (-)
        M104:       eject workspace
        
        -------Scaling--------
        G50:        disable scaling
        G51 S2      scale up by 2

        --Coordinate systems--
        G53         switch to MCS
        G54         switch to WCS #1
        G55         switch to WCS #2
        G56         switch to WCS #3
        G57         switch to WCS #4
        G58         switch to WCS #5
        G59         switch to WCS #6
        G59.1       switch to WCS #7
        G59.2       switch to WCS #8
        G59.3       switch to WCS #9
        ---
        G54 XnYn:   set WCS #1 to (n;n)
        G55 XnYn:   set WCS #2 to (n;n)
        G56 XnYn:   set WCS #3 to (n;n)
        G57 XnYn:   set WCS #4 to (n;n)
        G58 XnYn:   set WCS #5 to (n;n)
        G59 XnYn:   set WCS #6 to (n;n)
        G59.1 XnYn: set WCS #7 to (n;n)
        G59.2 XnYn: set WCS #8 to (n;n)
        G59.3 XnYn: set WCS #9 to (n;n)
    `;
}
