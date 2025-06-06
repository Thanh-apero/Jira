// Function to show a modal with details of reopened bugs by a specific person
function showReopenedBugsDetails(reopenerName) {
    event?.preventDefault?.();
    // Create modal HTML
    const modalId = 'reopenedBugsModal';
    let modal = document.getElementById(modalId);
    
    // If modal doesn't exist, create it
    if (!modal) {
        const modalHTML = `
            <div class="modal fade" id="${modalId}" tabindex="-1" aria-labelledby="reopenedBugsModalLabel" aria-hidden="true">
                <div class="modal-dialog modal-xl">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title" id="reopenedBugsModalLabel">Bugs Reopened by <span id="reopenerName"></span></h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <p>Loading reopened bugs data...</p>
                            <div id="reopenedBugsList"></div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Append to body
        document.body.insertAdjacentHTML('beforeend', modalHTML);
        modal = document.getElementById(modalId);
    }
    
    // Set the reopener name in the modal
    document.getElementById('reopenerName').textContent = reopenerName;
    
    // Get the project key from the stats modal
    const projectKey = document.getElementById('statsProjectKey').value;
    const jiraBaseUrl = document.getElementById('jiraUrlInput').value;
    
    // Get the start and end dates from the filters
    const startDate = document.getElementById('statsStartDate').value || null;
    const endDate = document.getElementById('statsEndDate').value || null;
    
    // Show the modal
    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();
    
    // Show loading indicator
    document.getElementById('reopenedBugsList').innerHTML = '<div class="text-center my-3"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div></div>';
    
    // Check if we already have statistics data in memory from window global variable
    if (window.currentStatisticsData) {
        // Use cached data instead of fetching again
        displayReopenedBugsDetails(window.currentStatisticsData, reopenerName, projectKey, jiraBaseUrl, startDate, endDate);
        return;
    }
    
    // If no cached data, fetch from API
    // Fetch reopened bugs for this person
    // Constructing the URL with parameters
    let url = `/api/project-statistics/${projectKey}`;
    const params = new URLSearchParams();
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    
    if (params.toString()) {
        url += `?${params.toString()}`;
    }
    
    // Create a unique request ID to track this specific request
    const requestId = `reopen_${projectKey}_${reopenerName}_${Date.now()}`;
    window.currentReopenRequest = requestId;
    
    fetch(url)
        .then(response => response.json())
        .then(data => {
            // Check if this is still the current request
            if (window.currentReopenRequest !== requestId) {
                console.log('Ignoring outdated reopened bugs response');
                return;
            }
            
            if (data.status === 'success' && data.statistics) {
                // Store statistics data in memory for future use
                window.currentStatisticsData = data.statistics;
                
                // Process and display the data
                displayReopenedBugsDetails(data.statistics, reopenerName, projectKey, jiraBaseUrl, startDate, endDate);
            } else {
                document.getElementById('reopenedBugsList').innerHTML = '<div class="alert alert-danger">Error loading reopened bugs data.</div>';
            }
        })
        .catch(error => {
            // Check if this is still the current request
            if (window.currentReopenRequest !== requestId) {
                console.log('Ignoring error from outdated reopened bugs request');
                return;
            }
            
            console.error('Error loading reopened bugs details:', error);
            // Show error and ensure all loading indicators are removed
            document.getElementById('reopenedBugsList').innerHTML = '<div class="alert alert-danger">Error loading reopened bugs data.</div>';
        });
}

// Function to display reopened bugs details using preloaded statistics data
function displayReopenedBugsDetails(statsData, reopenerName, projectKey, jiraBaseUrl, startDate, endDate) {
    // Extract reopened bugs from the statistics
    const reopenerStats = statsData.reopeners || [];
    const reopenedBugsCount = reopenerStats.find(r => r[0] === reopenerName)?.[1] || 0;
    
    // Find the reopened bugs by this person in the recent issues list
    const recentIssues = statsData.recent_issues || [];
    const reopenedBugs = [];
    
    // Search for reopened bugs with matching reopener
    for (const issue of recentIssues) {
        if (issue.type?.toLowerCase().includes('bug') && issue.was_reopened && issue.reopen_by === reopenerName) {
            reopenedBugs.push(issue);
        }
    }
    
    // Prepare the HTML output
    let outputHtml = `
        <div class="alert alert-info mb-3">
            <h5><i class="bi bi-info-circle me-2"></i>Reopened Bugs Statistics</h5>
            <p>${reopenerName} has reopened ${reopenedBugsCount} bug(s) ${startDate ? `since ${startDate}` : ''} 
            ${endDate ? `until ${endDate}` : ''} in project ${projectKey}.</p>
        </div>
    `;
    
    // Add JQL query reference
    outputHtml += `
        <div class="card mb-3">
            <div class="card-header">
                <h6 class="mb-0">JQL Query Reference</h6>
            </div>
            <div class="card-body">
                <pre>project = ${projectKey} AND type = Bug 
AND status CHANGED FROM ("Reviewing", "Review", "In Review", "Under Review", "Done", "Closed")
TO ("To Do", "Todo", "Backlog", "Open", "In Progress", "Reopened")
${startDate ? `AND updated >= "${startDate}"` : ""} 
${endDate ? `AND updated <= "${endDate}"` : ""}
</pre>
                <a href="${jiraBaseUrl}/issues/?jql=project%20%3D%20${projectKey}%20AND%20type%20%3D%20Bug%20AND%20status%20CHANGED%20FROM%20(%22Reviewing%22%2C%20%22Review%22%2C%20%22In%20Review%22%2C%20%22Under%20Review%22%2C%20%22Done%22%2C%20%22Closed%22)%20TO%20(%22To%20Do%22%2C%20%22Todo%22%2C%20%22Backlog%22%2C%20%22Open%22%2C%20%22In%20Progress%22%2C%20%22Reopened%22)${startDate ? `%20AND%20updated%20%3E%3D%20%22${startDate}%22` : ""}${endDate ? `%20AND%20updated%20%3C%3D%20%22${endDate}%22` : ""}%20AND%20updatedBy%20%3D%20%22${encodeURIComponent(reopenerName)}%22" class="btn btn-sm btn-primary" target="_blank">
                    <i class="bi bi-box-arrow-up-right me-1"></i>Open in Jira
                </a>
            </div>
        </div>
    `;
    
    // Add detailed stats about reopened bugs
    outputHtml += `
        <div class="card">
            <div class="card-header">
                <h6 class="mb-0">Reopened Bugs Details</h6>
            </div>
            <div class="card-body">
    `;
    
    // Create a project-specific endpoint to get real reopened bugs data
    // For this demonstration, we'll fetch all reopened bugs in the project from the API
    const detailsRequestId = `details_${Date.now()}`;
    window.currentDetailsRequest = detailsRequestId;
    
    // Show loading indicator for details section only
    outputHtml += `
        <div id="detailsLoadingIndicator" class="text-center my-3">
            <div class="spinner-border" role="status">
                <span class="visually-hidden">Loading bug details...</span>
            </div>
            <p class="mt-2">Loading bug details...</p>
        </div>
    `;
    
    // Set the initial HTML while we fetch details
    document.getElementById('reopenedBugsList').innerHTML = outputHtml;
    
    fetch(`/api/project-reopened-bugs/${projectKey}?reopener=${encodeURIComponent(reopenerName)}${startDate ? `&start_date=${startDate}` : ''}${endDate ? `&end_date=${endDate}` : ''}`)
    .then(response => response.json())
    .then(bugsData => {
        // Check if this is still the current details request
        if (window.currentDetailsRequest !== detailsRequestId) {
            console.log('Ignoring outdated bug details response');
            return;
        }
        
        // Remove the loading indicator from the output HTML
        outputHtml = outputHtml.replace(/<div id="detailsLoadingIndicator".*?<\/div>\s*<p.*?<\/p>\s*<\/div>/s, '');
        
        // Always make sure the final HTML is set without any loading indicators
        const finalHtmlPrep = outputHtml.replace(/<div class="text-center my-3"><div class="spinner-border".*?<\/div>/gs, '')
                                       .replace(/<div class="spinner-border.*?<\/div>/gs, '');
        
        if (bugsData.status === 'success' && bugsData.reopened_bugs && bugsData.reopened_bugs.length > 0) {
            // Add a table with the reopened bugs
            outputHtml += `
                <div class="table-responsive">
                    <table class="table table-sm table-striped">
                        <thead>
                            <tr>
                                <th>Key</th>
                                <th>Summary</th>
                                <th>Status</th>
                                <th>Assignee</th>
                                <th>Reopened From</th>
                                <th>Reopened To</th>
                                <th>Reopened On</th>
                            </tr>
                        </thead>
                        <tbody>
            `;
            
            bugsData.reopened_bugs.forEach(bug => {
                const bugKey = bug.key;
                const summary = bug.fields?.summary || 'No summary';
                const status = bug.fields?.status?.name || 'Unknown';
                const assignee = bug.fields?.assignee?.displayName || 'Unassigned';
                const reopenFrom = bug.reopen_from || 'Unknown';
                const reopenTo = bug.reopen_to || 'Unknown';
                const reopenTime = bug.reopen_time ? new Date(bug.reopen_time).toLocaleString() : 'Unknown';
                
                outputHtml += `
                    <tr>
                        <td><a href="${jiraBaseUrl}/browse/${bugKey}" target="_blank">${bugKey}</a></td>
                        <td>${summary}</td>
                        <td>${status}</td>
                        <td>${assignee}</td>
                        <td>${reopenFrom}</td>
                        <td>${reopenTo}</td>
                        <td>${reopenTime}</td>
                    </tr>
                `;
            });
            
            outputHtml += `
                        </tbody>
                    </table>
                </div>
            `;
        } else {
            // No data available or endpoint not implemented
            outputHtml += `
                <div class="alert alert-warning">
                    <p>No detailed data available for bugs reopened by ${reopenerName}.</p>
                    <p>To see the full list, please use the JQL query above or click "Open in Jira".</p>
                </div>
            `;
        }
        
        outputHtml += `
            </div>
        </div>
        `;
        
        // Set the final HTML - ensure all loading indicators are removed
        const finalHtml = outputHtml.replace(/<div id="detailsLoadingIndicator".*?<\/div>/gs, '')
                                   .replace(/<div class="text-center my-3"><div class="spinner-border".*?<\/div>/gs, '')
                                   .replace(/<div class="spinner-border.*?<\/div>/gs, '')
                                   .replace(/<span class="spinner-border.*?<\/span>/gs, '');
        document.getElementById('reopenedBugsList').innerHTML = finalHtml;
    })
    .catch(error => {
        // Check if this is still the current request
        if (window.currentDetailsRequest !== detailsRequestId) {
            console.log('Ignoring error from outdated bug details request');
            return;
        }
        
        console.error('Error fetching reopened bugs:', error);
        
        // Remove any loading indicator
        outputHtml = outputHtml.replace(/<div id="detailsLoadingIndicator".*?<\/div>\s*<p.*?<\/p>\s*<\/div>/s, '');
        
        // Fallback to basic display in case the API endpoint isn't implemented
        outputHtml += `
            <div class="alert alert-warning">
                <p>Could not load detailed data for bugs reopened by ${reopenerName}.</p>
                <p>To see the full list, please use the JQL query above or click "Open in Jira".</p>
            </div>
        </div>
        </div>
        `;
        
        // Set the HTML without the detailed table - ensure all loading indicators are removed
        const finalHtml = outputHtml.replace(/<div id="detailsLoadingIndicator".*?<\/div>/gs, '')
                                   .replace(/<div class="text-center my-3"><div class="spinner-border".*?<\/div>/gs, '')
                                   .replace(/<div class="spinner-border.*?<\/div>/gs, '')
                                   .replace(/<span class="spinner-border.*?<\/span>/gs, '');
        document.getElementById('reopenedBugsList').innerHTML = finalHtml;
    });
}