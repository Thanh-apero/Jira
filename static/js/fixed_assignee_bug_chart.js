// Fixed implementation of the updateAssigneeBugChart function
function updateAssigneeBugChart(assigneeBugStats) {
    const container = document.getElementById('assigneeBugStatsChart');
    
    if (!assigneeBugStats || assigneeBugStats.length === 0) {
        container.innerHTML = '<p class="text-center text-muted mt-5">No assignee bug data available</p>';
        return;
    }
    
    // Clear the container first
    container.innerHTML = '<canvas id="assigneeBugBarChart"></canvas>';
    
    // Create a Map to store assignee bug stats
    const statsMap = new Map();
    
    // Process assignee bug stats
    assigneeBugStats.forEach(stat => {
        const name = stat.name || 'Unassigned';
        statsMap.set(name, {
            total: stat.total || 0,
            reopened: stat.reopened || 0,
            key: stat.key || '',
            email: stat.email || '',
            avatarUrl: stat.avatarUrl || ''
        });
    });
    
    // Sort by total bugs (descending)
    const sortedStats = new Map([...statsMap.entries()].sort((a, b) => b[1].total - a[1].total));
    
    // Prepare data for chart
    const labels = [];
    const totalData = [];
    const reopenedData = [];
    
    // Create table for assignee bug stats
    const assigneeTableContainer = document.createElement('div');
    assigneeTableContainer.className = 'table-responsive mt-4';
    
    const assigneeTable = document.createElement('table');
    assigneeTable.className = 'table table-sm table-hover';
    
    // Create table header
    const assigneeThead = document.createElement('thead');
    assigneeThead.innerHTML = `
        <tr>
            <th>Assignee</th>
            <th>Total Bugs</th>
            <th>Reopened</th>
            <th>Actions</th>
        </tr>
    `;
    assigneeTable.appendChild(assigneeThead);
    
    // Create table body
    const assigneeTbody = document.createElement('tbody');
    
    // Use all assignees from the statsMap
    for (const [name, stats] of sortedStats.entries()) {
        labels.push(name);
        totalData.push(stats.total);
        reopenedData.push(stats.reopened);
        
        // Generate avatar URL if not present
        const avatarUrl = stats.avatarUrl || generateAvatar(name, stats.email);
        
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
        assigneeTbody.appendChild(row);
    }
    
    assigneeTable.appendChild(assigneeTbody);
    assigneeTableContainer.appendChild(assigneeTable);
    container.appendChild(assigneeTableContainer);
    
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
                    }
                }
            }
        }
    });
    
    // Adjust the height of the chart based on the number of assignees
    const chartHeight = Math.max(300, labels.length * 30); // Minimum 300px, 30px per assignee
    ctx.parentElement.style.height = `${chartHeight}px`;
}
