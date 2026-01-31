let selectedWorkspace = [0, 0];

function toggleImageTile(i, j, src) {
    let targetSrc = src;
    let cell = document.getElementById(`image-grid-${i}-${j}`);
    cell.innerHTML = "";

    if (!cell.classList.contains("active")) {
        let other_cell = document.getElementById(`image-grid-${selectedWorkspace[0]}-${selectedWorkspace[1]}`);
        if (other_cell) {
            other_cell.classList.remove("active");
        }
        cell.classList.add("active");
        selectedWorkspace = [i, j];
    }
    let img = document.createElement("img");
    img.src = targetSrc;
    cell.append(img);
}

function updateTiles() {
    let tileSize = document.getElementById("tiling-size").value;
    let imageTable = document.getElementById("image-grid");
    imageTable.innerHTML = "";

    if (selectedWorkspace[0] >= tileSize ||
        selectedWorkspace[1] >= tileSize) {
        selectedWorkspace = [0, 0];
    }

    for (let i = 0; i < tileSize; i += 1) {
        let tr = document.createElement("tr");
        for (let j = 0; j < tileSize; j += 1) {
            let td = document.createElement("td");
            td.id = `image-grid-${i}-${j}`;
            td.onclick = function () { toggleImageTile(i, j, "img/placeholder.png") };
            let img = document.createElement("img");
            img.src = "img/placeholder.png";

            if (selectedWorkspace[0] == i &&
                selectedWorkspace[1] == j) {
                td.classList.add("active");
            }

            td.append(img);
            tr.append(td);
        }
        imageTable.append(tr);
    }
}

function setupTiling() {
    let previewDiv = document.getElementById("preview-container");
    previewDiv.style.display = "flex";
    updateTiles();
}

function hideTilingPreview() {
    let previewDiv = document.getElementById("preview-container");
    previewDiv.style.display = "none";
}


async function setMachineTiling() {
    let tileSize = document.getElementById("tiling-size").value;
    const workspaceRequest = new Request('/plotter/tiling',
        {
            method: 'POST',
            body: tileSize
        }
    );
    const workspaceResponse = await fetch(workspaceRequest);

    if (!workspaceResponse.ok) {
        if (workspaceResponse.status === 503) {
            alert("The plotter is currently busy!");
            return;
        }
        throw new Error(`HTTP error, status: ${workspaceResponse.status}`);
    }

    let tileIdx = selectedWorkspace[0] * tileSize + selectedWorkspace[1] + 1;
    const workspaceSelectRequest = new Request('/plotter/tiling/switch',
        {
            method: 'POST',
            body: tileIdx
        }
    );

    const workspaceSelectResponse = await fetch(workspaceSelectRequest);

    if (!workspaceSelectResponse.ok) {
        if (workspaceSelectResponse.status === 503) {
            alert("The plotter is currently busy!");
            return;
        }
        throw new Error(`HTTP error, status: ${workspaceSelectResponse.status}`);
    }
}
