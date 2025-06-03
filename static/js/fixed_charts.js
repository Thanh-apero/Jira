// Fixed implementation of chart functions

// Function to update the assignee bug chart
function updateAssigneeBugChart(assigneeBugStats) {
    const container = document.getElementById('assigneeBugStatsChart');
    
    console.log('Assignee bug stats:', assigneeBugStats); // Debug log
    
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

// Function to update the participants chart
function updateParticipantsChart(participants) {
    const container = document.getElementById('participantsChartContainer');
    if (!participants || participants.length === 0) {
        container.innerHTML = '<p class="text-center text-muted mt-5">No participant data available</p>';
        return;
    }
    
    // Clear the container first
    container.innerHTML = '<canvas id="participantsBarChart"></canvas>';
    
    // Data is available. Ensure the canvas element is present.
    let ctx = document.getElementById('participantsBarChart');
    if (!ctx) {
        // Attempt to restore canvas
        console.warn("participantsBarChart canvas not found, attempting to restore.");
        container.innerHTML = '<canvas id="participantsBarChart"></canvas>';
        ctx = document.getElementById('participantsBarChart');
        if (!ctx) {
            console.error("Failed to ensure participantsBarChart canvas.");
            container.innerHTML = '<p class="text-center text-danger mt-5">Error: Chart canvas missing.</p>';
            if (participantsChart) { participantsChart.destroy(); participantsChart = null; }
            return;
        }
    }
    
    // Sort participants by total issue count
    participants.sort((a, b) => (b.issueCount || 0) - (a.issueCount || 0));
    
    // Take top 10 participants for the chart to avoid overcrowding
    const topParticipants = participants.slice(0, 10);
    
    // Process data for the chart
    const labels = [];
    const assignedData = [];
    const reportedData = [];
    const commentData = [];
    
    topParticipants.forEach(participant => {
        labels.push(participant.name);
        assignedData.push(participant.assignedCount || 0);
        reportedData.push(participant.reportedCount || 0);
        commentData.push(participant.commentCount || 0);
    });
    
    // Destroy existing chart if it exists
    if (participantsChart) {
        participantsChart.destroy();
    }
    
    // Create new chart
    participantsChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Assigned',
                    data: assignedData,
                    backgroundColor: '#4BC0C0',
                    borderColor: '#4BC0C0',
                    borderWidth: 1
                },
                {
                    label: 'Reported',
                    data: reportedData,
                    backgroundColor: '#FFCD56',
                    borderColor: '#FFCD56',
                    borderWidth: 1
                },
                {
                    label: 'Comments',
                    data: commentData,
                    backgroundColor: '#9966FF',
                    borderColor: '#9966FF',
                    borderWidth: 1
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const datasetLabel = context.dataset.label || '';
                            return `${datasetLabel}: ${context.parsed.y}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: 'Participants'
                    }
                },
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Count'
                    }
                }
            }
        }
    });
    
    // Adjust the height of the chart container based on the number of participants
    const chartHeight = Math.max(250, topParticipants.length * 25); // Minimum 250px, 25px per participant
    container.style.height = `${chartHeight}px`;
    
    // Now update the participants table to show ALL participants, not just the top 10
    const participantsTableBody = document.getElementById('participantsTable').getElementsByTagName('tbody')[0];
    participantsTableBody.innerHTML = '';
    
    if (participants && participants.length > 0) {
        participants.forEach(participant => {
            const row = participantsTableBody.insertRow();
            
            // Generate avatar URL if not present
            const avatarUrl = participant.avatarUrl || generateAvatar(participant.name, participant.email);
            
            // User with avatar
            const userCell = row.insertCell();
            userCell.innerHTML = `
                <div class="d-flex align-items-center">
                    <img src="${avatarUrl}" alt="${participant.name}" class="avatar-img me-2">
                    <span>${participant.name}</span>
                </div>
            `;
            
            // Assigned count
            row.insertCell().textContent = participant.assignedCount || 0;
            
            // Reported count
            row.insertCell().textContent = participant.reportedCount || 0;
            
            // Comment count
            row.insertCell().textContent = participant.commentCount || 0;
            
            // Total issues count
            row.insertCell().textContent = participant.issueCount || 0;
            
            // Actions
            const actionsCell = row.insertCell();
            actionsCell.innerHTML = `
                <button class="btn btn-sm btn-outline-primary" 
                        onclick="filterByParticipant('${participant.key || ''}', '${participant.name}')" 
                        title="Filter by this participant">
                    <i class="bi bi-funnel"></i>
                </button>
            `;
        });
    } else {
        participantsTableBody.innerHTML = '<tr><td colspan="6" class="text-center">No participants found</td></tr>';
    }
}
