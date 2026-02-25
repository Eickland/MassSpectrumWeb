// API URL
const API_BASE = '/api';

// Закрытие по кнопке Esc
document.addEventListener('keydown', (e) => {
    if (e.key === "Escape") closeModal();
});
// Load projects on page load
document.addEventListener('DOMContentLoaded', () => {
    loadProjects();
    loadSamples();

    // Import button handler
    const importBtn = document.getElementById('importBtn');
    if (importBtn) {
        importBtn.addEventListener('click', importData);
    }

    // Search input handler
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('input', filterSamples);
    }

    // Project filter handler
    const projectFilter = document.getElementById('projectFilter');
    if (projectFilter) {
        projectFilter.addEventListener('change', filterSamples);
    }
});

// Load projects
async function loadProjects() {
    try {
        const response = await fetch(`${API_BASE}/projects`);
        const projects = await response.json();
        
        const projectsList = document.getElementById('projects-list');
        const projectFilter = document.getElementById('projectFilter');
        
        if (projectsList) {
            projectsList.innerHTML = '';
            projects.forEach(project => {
                const projectEl = document.createElement('div');
                projectEl.className = 'project-item';
                projectEl.textContent = project.name;
                projectEl.dataset.project = project.name;
                projectEl.addEventListener('click', () => filterByProject(project.name));
                projectsList.appendChild(projectEl);
            });
        }

        if (projectFilter) {
            projectFilter.innerHTML = '<option value="all">All Projects</option>';
            projects.forEach(project => {
                const option = document.createElement('option');
                option.value = project.name;
                option.textContent = project.name;
                projectFilter.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Error loading projects:', error);
    }
}

// Load samples
async function loadSamples() {
    try {
        const response = await fetch(`${API_BASE}/samples`);
        const samples = await response.json();
        displaySamples(samples);
    } catch (error) {
        console.error('Error loading samples:', error);
    }
}

// Display samples in grid
function displaySamples(samples) {
    const samplesGrid = document.getElementById('samples-grid');
    const samplesList = document.getElementById('samples-list');
    
    const container = samplesGrid || samplesList;
    if (!container) return;

    container.innerHTML = '';

    samples.forEach(sample => {
        const card = createSampleCard(sample);
        container.appendChild(card);
    });
}

// Create sample card element
function createSampleCard(sample) {
    const card = document.createElement('div');
    card.className = 'sample-card';
    card.dataset.project = sample.project;
    card.dataset.name = sample.name;

    const mainGraph = sample.graphs.find(g => g.is_main) || sample.graphs[0];

    card.innerHTML = `
        <img src="${mainGraph ? mainGraph.file_path : ''}" 
            alt="${sample.name}" 
            class="sample-image"
            style="cursor: pointer;" 
            onclick="event.stopPropagation(); openModal('${mainGraph ? mainGraph.file_path : ''}', '${sample.name}')"
            onerror="this.src='data:image/svg+xml,...'">
        <div class="sample-info">
            <div class="sample-name">${sample.name}</div>
            <div class="sample-project">${sample.project}</div>
            ${sample.description ? `<div class="sample-description">${sample.description}</div>` : ''}
            
            ${sample.has_multiple ? `
                <div class="sample-graphs">
                    ${sample.graphs.map((graph, index) => `
                        <img src="${graph.file_path}" 
                            class="graph-thumbnail ${index === 0 ? 'active' : ''}"
                            onclick="event.stopPropagation(); showGraph('${sample.name}', ${index})">
                    `).join('')}
                </div>
            ` : ''}
        </div>
    `;

    card.addEventListener('click', () => {
        // В будущем здесь можно открыть детальную информацию
        console.log('Sample clicked:', sample.name);
    });

    return card;
}

// Filter samples by project
function filterByProject(project) {
    const cards = document.querySelectorAll('.sample-card');
    const projectItems = document.querySelectorAll('.project-item');
    
    projectItems.forEach(item => {
        item.classList.toggle('active', item.dataset.project === project);
    });

    cards.forEach(card => {
        if (project === 'Uncategorized') {
            card.style.display = card.dataset.project === 'Uncategorized' ? 'block' : 'none';
        } else {
            card.style.display = card.dataset.project === project ? 'block' : 'none';
        }
    });
}

// Filter samples by search and project
function filterSamples() {
    const searchTerm = document.getElementById('searchInput')?.value.toLowerCase() || '';
    const projectFilter = document.getElementById('projectFilter')?.value || 'all';
    
    const cards = document.querySelectorAll('.sample-card');
    
    cards.forEach(card => {
        const name = card.dataset.name.toLowerCase();
        const project = card.dataset.project;
        
        const matchesSearch = name.includes(searchTerm);
        const matchesProject = projectFilter === 'all' || project === projectFilter;
        
        card.style.display = matchesSearch && matchesProject ? 'block' : 'none';
    });
}

// Import new data
async function importData() {
    try {
        const response = await fetch(`${API_BASE}/import`, {
            method: 'POST'
        });
        
        if (response.ok) {
            const result = await response.json();
            alert(`Import successful: ${result.message}`);
            loadSamples();
        } else {
            alert('Import failed');
        }
    } catch (error) {
        console.error('Error importing data:', error);
        alert('Error importing data');
    }
}

// Show specific graph (for future multiple graphs feature)
function showGraph(sampleName, graphIndex) {
    console.log('Show graph', graphIndex, 'for sample', sampleName);
    // В будущем здесь будет логика для показа большого графика
}

function openModal(src, name) {
    const modal = document.getElementById('imageModal');
    const modalImg = document.getElementById('fullImage');
    const captionText = document.getElementById('caption');
    const downloadBtn = document.getElementById('downloadBtn');

    modal.style.display = "block";
    modalImg.src = src;
    captionText.innerHTML = name;

    // Настраиваем кнопку скачивания
    downloadBtn.href = src; // Путь к файлу (/data/...)
    downloadBtn.download = name; // Имя, под которым файл сохранится

    document.body.style.overflow = 'hidden';
}

function closeModal() {
    document.getElementById('imageModal').style.display = "none";
    // Возвращаем прокрутку
    document.body.style.overflow = 'auto';
}

