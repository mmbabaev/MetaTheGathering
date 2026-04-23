ï»¿$(document).ready(function () {

    $('#start-time').text(moment($('#start-time').attr('datetime')).utc().local());

    window.tourneyId = $('#tourneyChat').data('tourneyid');
    window.countdownTimer = 0;
    countDownTimerInit();
    if (window.loggedInList === undefined) {
        window.loggedInList = [];
    }
    loadPairings($("#tab_pairings").data('page'));

    new ClipboardJS('.copyLink', {
        text: function (trigger) {
            popupMessage('<b>Game DisplayName was copied!</b>', 1500, false);
            return trigger.getAttribute('data-nick');
        }
    });

    $("#signup-login-btn").on("click", function (e) {
        e.preventDefault();
        $('#login-button').click();
        $('#qEmail').focus();
        return false;
    });

    $("form#signupform").submit(function (e) {
        e.preventDefault();
        $("#signup-btn").attr('disabled', true);
        var tourneyId = $(this).data("tourneyid");
        var name = $("#signupname").val();
        var dci = $("#signupdci").val();
        var nick = $("#signupnick").val();
        var deckId = $("#submitdeck").val();
        $.ajax
            ({
                url: "/Tourney/AddSignup",
                type: "POST",
                dataType: "json",
                data: { tourneyId: tourneyId, playerName: name, playerDCI: dci, playerNick: nick, deckId: deckId },
                success: function (data) {
                    if (data === true) {
                        //addSignup(tourneyId); //SignalR version, no longer in use
                        location.reload();
                    }
                    else {
                        alert('Not signed up. Check your input fields.');
                        $("#signup-btn").removeAttr('disabled');
                    }
                },
                error: function (xhr, textStatus, errorThrown) {
                    //update failed - show error message
                    alert(textStatus + " " + errorThrown);
                    $("#signup-btn").removeAttr('disabled');
                }
            });
        return false;
    });

    //Add Result Tab Click
    $('.inner-content').on('click','.addresults-modal', function (e) {
        var tourneyId = $('#tourneyChat').data('tourneyid');
        //Reset Values before fetching from DB
        $('.drawRadioButtonLabel').removeClass('active');
        $('.playerOneRadioButtonLabel').removeClass('active');
        $('.playerTwoRadioButtonLabel').removeClass('active');
        $.ajax
            ({
                url: "/Tourney/TourneyGetPlayerMatchResults",
                type: "POST",
                dataType: "json",
                data: { tourneyId: tourneyId },
                success: function (data) {
                    if (data !== false) {
                        //fetch ok - populate fields
                        if (data.playerOneId === 0) { //bye
                            $('.p1-container').hide();
                            $('.p2points-container').hide();
                            $('.draws-container').hide();
                        }
                        else if (data.playerTwoId === 0) { //bye
                            $('.p2-container').hide();
                            $('.p1points-container').hide();
                            $('.draws-container').hide();
                        }
                        else {
                            $('.p1-container').show();
                            $('.p1points-container').show();
                            $('.p2points-container').show();
                            $('.p2-container').show();
                            $('.draws-container').show();
                        }
                            
                        if (data.p1result !== null) {
                            $('#resultsModal .p1result').show();
                            $('#resultsModal .p1result b').text(data.p1result);
                            if (data.p1draws > 0) {
                                $('#resultsModal .p1result span').text(' - ' + data.p1draws + ' draw');
                            }
                            else
                                $('#resultsModal .p1result span').text('');
                            if (data.p1resultextra !== "") {
                                $('#resultsModal .p1result div').text(data.p1resultextra).show();
                            }
                            else
                                $('#resultsModal .p1result div').text('').hide();
                        }
                        else {
                            $('#resultsModal .p1result').hide();
                            $('#resultsModal .p1result b, #resultsModal .p1result span').text('');
                            $('#resultsModal .p1result div').text('').hide();
                        }
                        if (data.p2result !== null) {
                            $('#resultsModal .p2result').show();
                            $('#resultsModal .p2result b').text(data.p2result);
                            if (data.p2draws > 0) {
                                $('#resultsModal .p2result span').text(' - ' + data.p2draws + ' draw');
                            }
                            else
                                $('#resultsModal .p2result span').text('');
                            if (data.p2resultextra !== "") {
                                $('#resultsModal .p2result div').text(data.p2resultextra).show();
                            }
                            else
                                $('#resultsModal .p2result div').text('').hide();
                        }
                        else {
                            $('#resultsModal .p2result').hide();
                            $('#resultsModal .p2result b, #resultsModal .p2result span').text('');
                            $('#resultsModal .p2result div').text('').hide();
                        }
                        $('#resultsModal #resultsRound').text(data.round);
                        $('#resultsModal input[name="playerOnePoints"][value="' + data.resultPlayerOne + '"]').prop('checked', true).parent().addClass('active');
                        $('#resultsModal input[name="playerTwoPoints"][value="' + data.resultPlayerTwo + '"]').prop('checked', true).parent().addClass('active');
                        $('#resultsModal input[name="draws"][value="' + data.numberOfDraws + '"]').prop('checked', true).parent().addClass('active');
                        $('#resultsModal #playerOneDrop').prop('checked', data.playerOneDropped);
                        $('#resultsModal #playerTwoDrop').prop('checked', data.playerTwoDropped);
                        $('#resultsModal #playerOneNoShow').prop('checked', data.playerOneNoShow);
                        $('#resultsModal #playerTwoNoShow').prop('checked', data.playerTwoNoShow);
                        var yourName = $('#tourneyChat').data('username');
                        var p1pre = '';
                        var p2pre = '';
                        if (data.playerOneName === yourName) {
                            p1pre = 'You';
                            p2pre = 'Opponent';
                            $('.p1-container').toggleClass('bg-light', true);
                            $('.p2-container').toggleClass('bg-light', false);
                            $('.playerOneNoShowBlock').hide();
                            $('.playerTwoNoShowBlock').show();
                        }
                        else if (data.playerTwoName === yourName) {
                            p1pre = 'Opponent';
                            p2pre = 'You';
                            $('.p1-container').toggleClass('bg-light', false);
                            $('.p2-container').toggleClass('bg-light', true);
                            $('.playerOneNoShowBlock').show();
                            $('.playerTwoNoShowBlock').hide();
                        }
                        $('#resultsModal .playerOneIntro').text(p1pre);
                        $('#resultsModal .playerTwoIntro').text(p2pre);
                        $('#resultsModal .playerOne').text(data.playerOneName);
                        $('#resultsModal .playerTwo').text(data.playerTwoName);
                        $('#resultsModal .matchId').val(data.matchId);
                    }
                },
                error: function (xhr, textStatus, errorThrown) {
                    //update failed - show error message
                    alert(textStatus + " " + errorThrown);
                }
            });
    });

    //Result Modal Click Save Results button
    $('#resultsModal').on('click', '.save-results', function () {
        var round = $('#resultsRound').text();
        var tourneyId = $('#tourneyChat').data('tourneyid');
        var matchId = $('#resultsModal .matchId').val();
        var playerOnePoints = $('#resultsModal input[name="playerOnePoints"]:checked').val();
        var playerTwoPoints = $('#resultsModal input[name="playerTwoPoints"]:checked').val();
        var draws = $('#resultsModal input[name="draws"]:checked').val();
        var playerOneDrop = $('#resultsModal #playerOneDrop').is(':checked');
        var playerTwoDrop = $('#resultsModal #playerTwoDrop').is(':checked');
        var playerOneNoShow = $('#resultsModal #playerOneNoShow').is(':checked');
        var playerTwoNoShow = $('#resultsModal #playerTwoNoShow').is(':checked');
        //If all points are 0 do not display completed results button
        var score = "";

        if (playerOnePoints === '2' && playerTwoPoints === '2') {
            alert('Error: Score Result is not valid');
            return false;
        }
        //Update the result table with results
        if (score.length === 0) {
            if (draws === '1' || draws === '2' || draws === '3') {
                score = playerOnePoints + ' - ' + playerTwoPoints + ' - ' + draws;
            } else {
                score = playerOnePoints + ' - ' + playerTwoPoints;
            }
        }

        var data = { tourneyId: tourneyId, Round: round, MatchId: matchId, ResultPlayerOne: playerOnePoints, ResultPlayerTwo: playerTwoPoints, NumberOfDraws: draws, PlayerOneDropped: playerOneDrop, PlayerTwoDropped: playerTwoDrop, PlayerOneNoShow: playerOneNoShow, PlayerTwoNoShow: playerTwoNoShow };
        console.log(data);
        //addResults(tourneyId, round, matchId, playerOnePoints, playerTwoPoints, draws, playerOneDrop, playerTwoDrop, playerOneNoShow, playerTwoNoShow); //SignalR version, no longer in use
        $.ajax
            ({
                url: "/Tourney/TourneyAddMatchResults",
                type: "POST",
                dataType: "json",
                data: data,
                success: function () {
                    popupMessage('Results added', 2500, false);
                },
                error: function (xhr, textStatus, errorThrown) {
                    popupMessage('Results add failed', 2500, true);
                }
            });
    });

    //StatusMessage Modal Click Save button
    $('#statusModal').on('click', '.save-status', function () {
        var tourneyId = $('#tourneyChat').data('tourneyid');
        var statusMessage = $('#statusInput').val();
        setStatusMessage(tourneyId, statusMessage);
    });

    //StatusMessage Modal Click Clear button
    $('#statusModal').on('click', '.clear-status', function () {
        $('#statusInput').val('');
    });

    if ($("time.timeago").length > 0) { $("time.timeago").timeago(); }
});

function updateLoggedIn(loggedIn) {
    window.loggedInList = loggedIn;
    refreshLoggedIn();
}

function refreshLoggedIn() {
    if (window.tourneyConnection) {
        $('#matchList .real-user').each(function (idx, elem) {
            var isOnline = false;
            var username = $(elem).data('username');
            window.loggedInList.forEach(function (element, index) {
                if (element === username)
                    isOnline = true;
            });
            $(elem).toggleClass('text-success', isOnline).toggleClass('fa-user', isOnline).toggleClass('text-danger', !isOnline).toggleClass('fa-user-times', !isOnline);
        });
    }
}

function reloadPlayers(username) {
    var user = $('#tourneyChat').data('username');
    if (username.length > 0 && username === user) {
        location.reload();
    }
    else {
        console.log('player added/removed');
    }
}

function loadPairings(p) {
    var currentPage = $("#tab_pairings").data('page');
    var page = p !== "";
    if (currentPage === p) {
        var tourneyId = $("#tourneyChat").data('tourneyid');
        $("#tab_pairings").load('/Tourney/RoundTourneyPublicPairings?id=' + tourneyId + (page ? '&p=' + p : ''), function () {
            refreshLoggedIn();

            var player = $('#statusArea').data('playerid');
            var oppo = $('#matchList tbody tr[data-p1="' + player + '"]').data('p2');
            if (oppo === undefined)
                oppo = $('#matchList tbody tr[data-p2="' + player + '"]').data('p1');
            if (oppo === undefined)
                $('#statusArea').data('oppoid', '');
            else
                $('#statusArea').data('oppoid', oppo);

            if (player) {
                $.ajax
                    ({
                        url: "/Tourney/TourneyGetPlayerStatusMessage",
                        type: "POST",
                        dataType: "json",
                        data: { tourneyId: tourneyId },
                        success: function (data) {
                            if (data !== false) {
                                $('#statusArea .oppostatus b').text(data.oppoUsername);
                                receiveStatusMessage(oppo, data.oppoMessage, data.oppoTime);
                                receiveStatusMessage(player, data.yourMessage, data.yourTime);
                            }
                            else {
                                $('#statusArea .oppostatus b').text('');
                                receiveStatusMessage('', '', null);
                            }
                        }
                    });
            }
        });
    }
}

function getRandomInt(max) {
    return Math.floor(Math.random() * Math.floor(max));
}

function newPairings() {
    setTimeout(function () {
        location = location.pathname;
    }, getRandomInt(10000));
}

function timeStarted(seconds) {
    if (seconds > 0) {
        countDownTimerStart(seconds, seconds);
    }
    else {
        clearInterval(window.countdownTimer);
        $('#countdown').hide();
        sessionStorage.removeItem(window.tourneyId + ':timersecondsmax');
        sessionStorage.removeItem(window.tourneyId + ':timersecondsremaining');
    }
}

function countDownTimerInit() {
    var secondsRemaining = $('#countdown').data('secondsremaining');
    if (secondsRemaining > 0) {
        var secondsMax = $('#countdown').data('secondsmax');
        sessionStorage.setItem(window.tourneyId + ':timersecondsmax', secondsMax);
        sessionStorage.setItem(window.tourneyId + ':timersecondsremaining', secondsRemaining);
        countDownTimerStart(secondsMax, secondsRemaining);
    }
    else {
        sessionStorage.removeItem(window.tourneyId + ':timersecondsmax');
        sessionStorage.removeItem(window.tourneyId + ':timersecondsremaining');
    }
}

function countDownTimerStart(seconds, secondsremaining) {
    $('#countdown').show();
    var countdown_number = document.getElementById('countdown_number');
    countdown_number.setAttribute("aria-valuemax", seconds);
    sessionStorage.setItem(window.tourneyId + ':timersecondsmax', seconds);
    if (secondsremaining >= 0)
        seconds = secondsremaining;
    sessionStorage.setItem(window.tourneyId + ':timersecondsremaining', seconds);
    countdown_number.innerHTML = '00:00';
    countdown_number.className = countdown_number.className.replace("progress-bar-warning", "progress-bar-info");
    function secondPassed() {
        var countdown_number = $('#countdown_number');
        var minutes = Math.round((seconds - 30) / 60);
        var remainingSeconds = seconds % 60;
        if (remainingSeconds < 10) {
            remainingSeconds = "0" + remainingSeconds;
        }
        var max_seconds = countdown_number.attr("aria-valuemax");
        countdown_number.html(minutes + ":" + remainingSeconds);
        countdown_number.attr("aria-valuenow", max_seconds - seconds);
        countdown_number.css("width", (max_seconds - seconds) / max_seconds * 100 + "%");
        if (seconds === 0) {
            clearInterval(window.countdownTimer);
            countdown_number.html("Time!");
            countdown_number.removeClass("progress-bar-info");
            countdown_number.addClass("progress-bar-warning");
        } else {
            seconds--;
            sessionStorage.setItem(window.tourneyId + ':timersecondsremaining', seconds);
        }
    }
    clearInterval(window.countdownTimer);
    window.countdownTimer = setInterval(secondPassed, 1000);
}

function receiveStatusMessage(playerId, message, time) {
    var hidden = message === "";
    if (!hidden)
        message = message.replace('"', '&quot;');
    var oppo = $('#statusArea').data('oppoid') === playerId;
    var you = $('#statusArea').data('playerid') === playerId;
    if (oppo) {
        $('#statusArea .oppostatus').toggleClass('d-none', hidden);
        $('#statusArea .oppostatus time').text('').attr('datetime', time).timeago('updateFromDOM');
        $('#statusArea .oppostatus span').text(message);
    }
    if (you) {
        $('#statusArea .yourstatus').toggleClass('d-none', hidden);
        $('#statusArea .yourstatus time').text('').attr('datetime', time).timeago('updateFromDOM');
        $('#statusArea .yourstatus span').text(message);
    }
}
