// Fixed implementation of the updateParticipantsChart function
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
                    backgroundColor: '#FF9F40',
                    borderColor: '#FF9F40',
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
