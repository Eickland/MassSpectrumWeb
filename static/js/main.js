// API URL
const API_BASE = '/api';

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

    // Get main graph or first graph
    const mainGraph = sample.graphs.find(g => g.isMain) || sample.graphs[0];

    card.innerHTML = `
        <img src="/data/${mainGraph ? mainGraph.filePath : ''}" 
             alt="${sample.name}" 
             class="sample-image"
             onerror="this.src='data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22300%22%20height%3D%22200%22%20viewBox%3D%220%200%20300%20200%22%3E%3Crect%20width%3D%22300%22%20height%3D%22200%22%20fill%3D%22%23f0f0f0%22%2F%3E%3Ctext%20x%3D%22150%22%20y%3D%22100%22%20font-family%3D%22Arial%22%20font-size%3D%2214%22%20fill%3D%22%23999%22%20text-anchor%3D%22middle%22%3ENo%20Image%3C%2Ftext%3E%3C%2Fsvg%3E'">
        <div class="sample-info">
            <div class="sample-name">${sample.name}</div>
            <div class="sample-project">${sample.project}</div>
            ${sample.description ? `<div class="sample-description">${sample.description}</div>` : ''}
            
            ${sample.hasMultiple ? `
                <div class="sample-graphs">
                    ${sample.graphs.map((graph, index) => `
                        <img src="/data/${graph.filePath}" 
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