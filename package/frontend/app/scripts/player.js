let currentImage = "";
let currentSketch = "";
let blobUrls = "";
const selectedWorkspaces = [];
let fileTable;

function toggleImageTile(i, j, src) {
    let targetSrc = src;
    let cell = document.getElementById(`image-grid-${i}-${j}`);
    cell.innerHTML = "";

    let tileSize = document.getElementById("tiling-size").value;
    let tileIdx = i * tileSize + j + 1;

    if (cell.classList.contains("active")) {
        targetSrc = "img/placeholder.png";
        cell.classList.remove("active");
        let indexToRemove = selectedWorkspaces.indexOf(tileIdx);
        selectedWorkspaces.splice(indexToRemove, 1);
    } else {
        if (!cell.classList.contains('uninitialized')) {
            cell.classList.add("active");
            selectedWorkspaces.push(tileIdx);
        } else {
            cell.classList.remove('uninitialized');
        }
    }
    let img = document.createElement("img");
    img.src = targetSrc;
    cell.append(img);
}

function updateImageTiles() {
    selectedWorkspaces.length = 0;
    let tileSize = document.getElementById("tiling-size").value;
    let imageTable = document.getElementById("image-grid");
    imageTable.innerHTML = "";

    for (let i = 0; i < tileSize; i += 1) {
        let tr = document.createElement("tr");
        for (let j = 0; j < tileSize; j += 1) {
            let td = document.createElement("td");
            td.id = `image-grid-${i}-${j}`;
            td.classList.add('uninitialized');
            td.onclick = function () { toggleImageTile(i, j, currentImage) };
            tr.append(td);
        }
        imageTable.append(tr);
    }
    for (let i = 0; i < tileSize; i += 1) {
        for (let j = 0; j < tileSize; j += 1) {
            toggleImageTile(i, j, "img/placeholder.png");
        }
    }
    toggleImageTile(0, 0, currentImage);
}

function openPreview(sketchName, previewImgSrc) {
    currentSketch = sketchName;
    currentImage = previewImgSrc;

    let previewDiv = document.getElementById("preview-container");
    previewDiv.style.display = "flex";
    updateImageTiles();
}

async function playSketch() {
    if (!selectedWorkspaces.length) {
        alert("No workspace selected!");
        return;
    }

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

    const playRequest = new Request('/plotter/play',
        {
            method: 'POST',
            body: JSON.stringify({
                'sketch_name': currentSketch,
                'workspaces': selectedWorkspaces
            })
        }
    );

    const playResponse = await fetch(playRequest);
    if (!playResponse.ok) {
        if (playResponse.status === 503) {
            alert("The plotter is currently busy!");
            return;
        }
        throw new Error(`HTTP error, status: ${playResponse.status}`);
    }
}

function hidePreview() {
    let previewDiv = document.getElementById("preview-container");
    previewDiv.style.display = "none";
}

let tilingInputHandler = null;


async function preloadImagesToBlobs(urls, delayMs = 100) {
    const images = [];

    for (const url of urls) {
        try {
            const response = await fetch(url, { cache: "no-store" }); // avoid duplicate browser caching
            if (!response.ok) throw new Error(`Failed to fetch ${url}`);

            const blob = await response.blob(); // get the binary data
            const blobUrl = URL.createObjectURL(blob); // create local URL
            images.push(blobUrl);

            console.log(`Loaded ${url} into memory`);
        } catch (err) {
            console.error(err);
        }
        await new Promise(r => setTimeout(r, delayMs));
    }

    return images;
}


async function handleTableClick(event) {
    const playButton = event.target.closest('.play-button');
    const downloadButton = event.target.closest('.download-button');
    const deleteButton = event.target.closest('.delete-button');

    // If not a button we care about, ignore
    if (!playButton && !downloadButton && !deleteButton) return;

    // Find the row (closest tr)
    const row = event.target.closest('tr');
    if (!row) return;

    const fileUrl = row.dataset.url;

    if (playButton) {
        openPreview(fileUrl, "img/placeholder.png");
    }
    else if (downloadButton) {
        window.open(fileUrl, '_blank');
    }
    else if (deleteButton) {
        if (confirm(`Delete ${fileUrl.split("/").pop()}?`)) {
            const deleteRequest = new Request('/plotter/files',
                {
                    method: 'DELETE',
                    body: fileUrl.split("/").pop()
                }
            );
            await fetch(deleteRequest);
            updateFileList();
        }
    }
}


function updateFileList() {
    fetch('/plotter/files')
        .then((response) => {
            if (!response.ok) {
                throw new Error(`Could not get files, ${response.status}`);
            }
            return response.json();
        })
        .then((json) => {
            let fileManagerBody = document.getElementById("file-manager-body");
            fileManagerBody.innerHTML = "";

            json.forEach(element => {
                let fileRow = document.createElement('tr');
                fileRow.classList.add("file-entry");
                fileRow.dataset.url = element['name'];

                let nameCell = document.createElement('td');
                nameCell.innerText = element['name'].split("/").pop();
                fileRow.appendChild(nameCell);

                let sizeCell = document.createElement('td');
                sizeCell.innerText = (element['size'] / 1000).toFixed(1).toString() + "KB";
                fileRow.appendChild(sizeCell);

                let dateCell = document.createElement('td');
                dateCell.innerText = (new Date((element['created'] + 946684800) * 1000)).toLocaleString();
                fileRow.appendChild(dateCell);

                let actionsCell = document.createElement('td');
                actionsCell.classList.add("player-actions");

                let playButton = document.createElement('img');
                playButton.src = blobUrls[0];
                playButton.classList.add("play-button");

                let downloadFileButton = document.createElement('img');
                downloadFileButton.src = blobUrls[1];
                downloadFileButton.classList.add("download-button");

                /*let previewButton = document.createElement('img');
                previewButton.src = blobUrls[2];
                previewButton.classList.add("preview-button");*/

                let deleteButton = document.createElement('img');
                deleteButton.src = blobUrls[2]; //3
                deleteButton.classList.add("delete-button");

                actionsCell.appendChild(playButton);
                actionsCell.appendChild(downloadFileButton);
                //actionsCell.appendChild(previewButton);
                actionsCell.appendChild(deleteButton);
                fileRow.appendChild(actionsCell);

                fileManagerBody.appendChild(fileRow);
            });
        });
}


export async function main() {
    fileTable = document.getElementById('file-manager');
    fileTable.addEventListener('click', handleTableClick);

    let tilingSizeInput = document.getElementById("tiling-size");
    tilingInputHandler = () => { updateImageTiles(); };
    tilingSizeInput.addEventListener("input", tilingInputHandler);

    const closePreviewBtn = document.getElementById("close-preview");
    closePreviewBtn.addEventListener("click", hidePreview);

    const playSketchBtn = document.getElementById("play-sketch");
    playSketchBtn.addEventListener("click", playSketch);

    let playButtonSrc = "img/play-button-icon.png";
    let downloadFileButtonSrc = "img/download-file-icon.png";
    //let previewButtonSrc = "img/eye-icon.png";
    let deleteButtonSrc = "img/delete-icon.png";

    if (!blobUrls)
        blobUrls = await preloadImagesToBlobs([playButtonSrc, downloadFileButtonSrc, /*previewButtonSrc,*/ deleteButtonSrc]);

    let fileInput = document.getElementById('file-upload');
    fileInput.addEventListener('change', async function () {
        if (fileInput.files.length === 0) {
            return;
        }

        const file = fileInput.files[0];
        const chunkSize = 2 * 1024;
        const totalChunks = Math.ceil(file.size / chunkSize);

        let files = Array.from(
            document.getElementById("file-manager-body").getElementsByClassName("file-entry")).map(
                tr => tr.dataset.url.split('/').pop());

        if (files.includes(file.name)) {
            if (!confirm(`Overwrite ${file.name}?`)) {
                return;
            }
            const deleteRequest = new Request('/plotter/files',
                {
                    method: 'DELETE',
                    body: file.name
                }
            );
            await fetch(deleteRequest);
        }

        console.log(`Uploading "${file.name}" in ${totalChunks} chunks...`);

        for (let i = 0; i < totalChunks; i++) {
            const start = i * chunkSize;
            const end = Math.min(file.size, start + chunkSize);
            const chunk = file.slice(start, end); // Blob chunk
            const formData = new FormData();

            formData.append(`chunk_${i + 1}`, chunk, file.name);

            try {
                const response = await fetch('/plotter/files', {
                    method: 'POST',
                    body: formData,
                });

                if (!response.ok) throw new Error(`Chunk ${i + 1} failed`);
                console.log(`Uploaded chunk ${i + 1}/${totalChunks}`);
            } catch (err) {
                console.error('Error uploading chunk:', err);
                alert('Upload failed, check console for details.');
                return;
            }
        }
        updateFileList();
    });

    updateFileList();
}

export function cleanup() {
    let tilingSizeInput = document.getElementById("tiling-size");
    tilingSizeInput.removeEventListener("input", tilingInputHandler);
    tilingInputHandler = null;

    document.getElementById("close-preview").removeEventListener("click", hidePreview);
    document.getElementById("play-sketch").removeEventListener("click", playSketch);

    fileTable.removeEventListener('click', handleTableClick);
}
