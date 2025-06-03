// Avatar generation function
function generateAvatar(name, email) {
    // Generate a consistent color based on the name
    let hash = 0;
    for (let i = 0; i < name.length; i++) {
        hash = name.charCodeAt(i) + ((hash << 5) - hash);
    }
    
    // If email is available, use Gravatar
    if (email && email.includes('@')) {
        // Simple hash for demo - in production use a proper MD5 library
        return `https://www.gravatar.com/avatar/${Math.abs(hash).toString(16)}?d=identicon&s=32`;
    }
    
    // Otherwise use a consistent avatar based on name
    return `https://ui-avatars.com/api/?name=${encodeURIComponent(name)}&background=${Math.abs(hash).toString(16).substr(0, 6)}&color=fff&size=32`;
}

// Enhanced filterByParticipant function
function filterByParticipant(participantKey, participantName) {
    console.log('Filtering by participant:', participantKey, participantName);
    
    // Set the filter dropdown to the selected participant
    const participantFilter = document.getElementById('statsParticipantFilter');
    if (participantFilter) {
        // First check if the option exists, if not add it
        let optionExists = false;
        for (let i = 0; i < participantFilter.options.length; i++) {
            if (participantFilter.options[i].value === participantKey) {
                optionExists = true;
                break;
            }
        }
        
        if (!optionExists && participantKey) {
            const option = document.createElement('option');
            option.value = participantKey;
            option.textContent = participantName;
            participantFilter.appendChild(option);
        }
        
        // Set the value
        participantFilter.value = participantKey;
    }
    
    // Update the filter label
    const filterLabel = document.getElementById('currentParticipantFilter');
    if (filterLabel) {
        filterLabel.textContent = participantName || 'All';
    }
    
    // Apply the filter
    applyStatsFilters();
}

// Enhanced updateAssigneeBugChart function
function enhancedUpdateAssigneeBugChart(assigneeBugStats) {
    const container = document.getElementById('assigneeBugStatsChart');
    if (!container) {
        console.error("Assignee bug chart container not found");
        return;
    }

    const spinner = document.getElementById('assigneeBugSpinnerContainer');
    if (spinner) {
        spinner.remove();
    }
    
    // If no assignee data or empty array
    if (!assigneeBugStats || assigneeBugStats.length === 0) {
        container.innerHTML = '<p class="text-center text-muted mt-5">No bug assignee data available</p>';
        if (assigneeBugChart) {
            assigneeBugChart.destroy();
            assigneeBugChart = null;
        }
        return;
    }
    
    // Create a table to display assignees with avatars and bug counts
    const assigneeTable = document.createElement('div');
    assigneeTable.className = 'table-responsive mt-4';
    const table = document.createElement('table');
    table.className = 'table table-sm table-striped';
    
    // Create table header
    const thead = document.createElement('thead');
    thead.innerHTML = `
        <tr>
            <th>Assignee</th>
            <th>Total Bugs</th>
            <th>Reopened Bugs</th>
            <th>Actions</th>
        </tr>
    `;
    table.appendChild(thead);
    
    // Create table body
    const tbody = document.createElement('tbody');
    
    // Process data for the chart
    const labels = [];
    const totalData = [];
    const reopenedData = [];
    
    // Add rows for each assignee
    for (const [name, stats] of assigneeBugStats) {
        labels.push(name);
        totalData.push(stats.total);
        reopenedData.push(stats.reopened);
        
        // Generate avatar URL if not present
        const avatarUrl = stats.avatarUrl || generateAvatar(name, stats.email || '');
        
        // Add row to table
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>
                <div class="d-flex align-items-center">
                    <img src="${avatarUrl}" alt="${name}" class="avatar-img me-2">
                    <span>${name}</span>
                </div>
            </td>
            <td>${stats.total}</td>
            <td>${stats.reopened}</td>
            <td>
                <button class="btn btn-sm btn-outline-primary" 
                        onclick="filterByParticipant('${stats.key || ''}', '${name}')" 
                        title="Filter by this assignee">
                    <i class="bi bi-funnel"></i>
                </button>
            </td>
        `;
        tbody.appendChild(row);
    }
    
    table.appendChild(tbody);
    assigneeTable.appendChild(table);
    
    // Data is available. Ensure the canvas element is present.
    let ctx = document.getElementById('assigneeBugBarChart');
    if (!ctx) {
        // Attempt to restore canvas
        console.warn("assigneeBugBarChart canvas not found, attempting to restore.");
        container.innerHTML = '<canvas id="assigneeBugBarChart"></canvas>';
        ctx = document.getElementById('assigneeBugBarChart');
        if (!ctx) {
            console.error("Failed to ensure assigneeBugBarChart canvas.");
            container.innerHTML = '<p class="text-center text-danger mt-5">Error: Chart canvas missing.</p>';
            if (assigneeBugChart) { assigneeBugChart.destroy(); assigneeBugChart = null; }
            return;
        }
    }
    
    // Destroy existing chart if it exists
    if (assigneeBugChart) {
        assigneeBugChart.destroy();
    }
    
    // Create new chart
    assigneeBugChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Total Bugs',
                    data: totalData,
                    backgroundColor: '#36A2EB',
                    borderColor: '#36A2EB',
                    borderWidth: 1
                },
                {
                    label: 'Reopened Bugs',
                    data: reopenedData,
                    backgroundColor: '#FF6384',
                    borderColor: '#FF6384',
                    borderWidth: 1
                }
            ]
        },
        options: {
            responsive: true,
            indexAxis: 'y',  // Horizontal bar chart
            maintainAspectRatio: false,
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const datasetLabel = context.dataset.label || '';
                            return `${datasetLabel}: ${context.parsed.x}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Number of Bugs'
                    },
                    stacked: false
                },
                y: {
                    stacked: false
                }
            }
        }
    });
    
    // Adjust the height of the chart container based on the number of assignees
    const chartHeight = Math.max(250, assigneeBugStats.length * 25); // Minimum 250px, 25px per assignee
    container.style.height = `${chartHeight}px`;
    
    // Add the table below the chart
    container.appendChild(assigneeTable);
}
