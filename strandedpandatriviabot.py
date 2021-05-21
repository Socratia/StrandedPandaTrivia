"""
-*- coding: utf-8 -*-
@author: socratio
@inspiration: drew original inspiration from cleartonic twitchtriviabot. Almost nothing left in this code from that project.

"""
import json
from twitchio import websocket
from twitchio.ext import commands
import yaml
import asyncio
import os
import random

class ChatBot(commands.Bot):
        
    def __init__(self):
        #load the auth and connect to twitch
        with open(os.path.join(os.getcwd(),'config','auth_config.yml')) as auth:
            self.auth = yaml.safe_load(auth)
        super().__init__(irc_token=f"{self.auth['pass']}", client_id='...', nick=f"{self.auth['nick']}", prefix='!',initial_channels=[f"{self.auth['chan']}"])

        #load the trivia configuration
        with open(os.path.join(os.getcwd(),'config','trivia_config.yml')) as config:
            self.trivia_config = yaml.safe_load(config)
        
        #create admins array, empty players and questions arrays, boolean variables, and empty answer messages object
        self.admins = [i.strip() for i in self.trivia_config['admins'].split(",")]
        self.players = []
        self.questionlist = []
        self.active_game = False
        self.questionisactive = False
        self.active_question = False
        self.scoringopen = False
        self.answermessages = {}

        #load the scoreboard, set the list of past winners, increment the game number
        self.refresh_scores()
        try:
            self.pastwinners = self.scores[f'Season {self.trivia_config["season"]}']['shirtwinners']
        except:
            self.scores[f'Season {self.trivia_config["season"]}'] = {"gamesplayed":0, "shirtwinners":[], "scoreboard":{}}
            self.pastwinners = self.scores[f'Season {self.trivia_config["season"]}']['shirtwinners']
        self.game_number = self.scores[f'Season {self.trivia_config["season"]}']['gamesplayed']+1

        #load the questions and populate the questions array
        with open(os.path.join(os.getcwd(),'config','triviaset.json')) as self.questions:
            self.questions = json.load(self.questions)
        for question in self.questions.items():
            self.questionlist.append(Question(question))
        
        #populate the players array
        for player in self.scores[f'Season {self.trivia_config["season"]}']['scoreboard'].items():
            self.players.append(Player(player))

    
    #updates the scoreboard dict object
    def refresh_scores(self):
        with open(os.path.join(os.getcwd(),'config','scores',"scoreboard.json")) as scores:
            self.scores = json.load(scores)
    
    #clears json of scores for this game, sorts and adds scores back to json, resulting in sorted scores every time. Also saves scores to scoreboard file
    def commit_scores(self):
        self.scores[f'Season {self.trivia_config["season"]}'][f'Game {self.game_number}'] = {}
        self.scores[f'Season {self.trivia_config["season"]}']['scoreboard'] = {}
        for player in sorted(self.players, key=lambda player:player.seasonpoints, reverse=True):
            self.scores[f'Season {self.trivia_config["season"]}']['scoreboard'][player.name] = player.seasonpoints
        for player in sorted(self.players, key=lambda player:player.gamepoints, reverse=True):
            self.scores[f'Season {self.trivia_config["season"]}'][f'Game {self.game_number}'][player.name] = player.gamepoints
        with open(os.path.join(os.getcwd(),'config','scores',"scoreboard.json"),'w') as outfile:
            json.dump(self.scores, outfile, indent=4)    
        
    
    #Broadcast ready state to twitch channel
    async def event_ready(self):
        print(f'Ready | {self.nick}')
        ws = bot._ws
        await ws.send_privmsg(self.initial_channels[0],"I have indeed been uploaded, sir.")
    
    #major message reading function
    async def event_message(self, message):
        if message.author != self.nick:
            print(f'{message.author.name}: {message.content}')
            await self.handle_commands(message)
            if self.scoringopen == True and not message.content.startswith('!'):
                if message.author.name in self.answermessages:
                    del self.answermessages[message.author.name]
                self.answermessages[message.author.name] = message.content
    
    @commands.command(name='test')
    async def test(self, ctx):
        await ctx.send(f'Hello {ctx.author.name}!')
    
    #TRIVIA COMMANDS AND PROCEDURES
    @commands.command(name='start')
    #!Start command starts the trivia game
    async def start(self, ctx):
        if ctx.author.name in self.admins and not self.active_game:
            self.active_game = True
            print('Starting Game.')
            await ctx.send("Game starts in 15 seconds. Watch the chat for the question. Good luck!")
            await asyncio.sleep(15)
            if self.active_game:
                await self.callquestion()
    
    @commands.command(name='next')
    #!next starts the process of asking the next question after 10 seconds and scoring after 20 seconds
    async def nextq(self, ctx):
        if ctx.author.name in self.admins and not self.questionisactive:
            self.questionisactive = True
            print('Received call for next question.')
            await ctx.send("Next question coming in 10 seconds. Keep an eye on the chat!")
            await asyncio.sleep(10)
            if self.active_game:
                await self.callquestion()
        else:
            print('Received call for next question, but an active question exists or it is not an admin. Ignoring call.')
    
    @commands.command(name='end')
    #!end ends this game of trivia, commits scores to json, and refreshes the scores
    async def endtrivia(self, ctx):
        if ctx.author.name in self.admins and self.active_game:
            print("Ending game.")
            self.scoringopen = False
            self.active_game = False
            self.active_question = False
            if any(i.gamepoints > 0 for i in self.players):
                for player in sorted(self.players, key=lambda x:x.gamepoints, reverse=True):
                    if player.name not in self.scores[f'Season {self.trivia_config["season"]}']['shirtwinners']:
                        self.scores[f'Season {self.trivia_config["season"]}']['shirtwinners'].append(player.name)
                        self.pastwinners.append(player.name)
                        break
                self.scores[f'Season {self.trivia_config["season"]}']['gamesplayed'] = self.game_number
                await ctx.send(f"Ending this game of trivia. Congratulations to {self.pastwinners[-1]} on the new shirt! I hope everyone had fun!")
                self.commit_scores()
                self.refresh_scores()
            
    @commands.command(name='bonus')
    #!bonus reads the message, finds the user targeted for bonus points, finds the point value of the bonus, assigns the extra points if the player exists or creates them if not, and refreshes the scores
    async def bonus(self, ctx):
        if ctx.author.name in self.admins:
            print(f"Received call for bonus points from {ctx.author.name}.")
            bonustarget = ctx.message.content.split()[1].lower()
            bonuspoints = int(ctx.message.content.split()[2])
            if any(bonustarget == player.name for player in self.players):
                for player in self.players:
                    if player.name == bonustarget:
                        player.gamepoints += int(bonuspoints)
                        returnstr = player.gamepoints
            else:
                print(f'Player {bonustarget} does not exist. Creating.')
                user = Player(bonustarget,bonuspoints)
                self.players.append(user)
            self.commit_scores()
            self.refresh_scores()
            await ctx.send(f'Player {bonustarget} received {bonuspoints} bonus points. Their new total is {returnstr} points.')
            
    @commands.command(name='lasttop5')
    #!lasttop5 calls the top 5 scores from the last game played
    async def lasttop5(self, ctx):
        if ctx.author.name in self.admins:
            returnstr = "TOP 5 SCORES FOR THE LAST GAME:\t"
            lastgameno = self.scores[f'Season {self.trivia_config["season"]}']['gamesplayed']
            lastgamescores = self.scores[f'Season {self.trivia_config["season"]}'][f'Game {lastgameno}']
            for score in sorted(lastgamescores.items(), key=lambda x:x[1], reverse=True)[:5]:
                returnstr += f"{score[0]}: {score[1]}  "
            await ctx.send(returnstr)
            
    async def callquestion(self):
        self.active_question = self.questionlist.pop(0)
        self.scoringopen = True
        self.answermessages = {}
        ws = bot._ws
        await ws.send_privmsg(self.initial_channels[0],f"Question {self.active_question.questionno}: {self.active_question.question}")
        await asyncio.sleep(20)
        self.scoringopen = False
        await self.scorequestion()
        self.questionisactive = False
        
    async def scorequestion(self):
        self.scoringopen = False
        ws = bot._ws
        self.point_dict = {}
        returnstr = f"The answer was **{self.active_question.answers[0]}**.\t"
        #check that all players that answered exist as Player objects
        for name in self.answermessages.keys():
            if not any(player.name == name for player in self.players):
                print(f'Player {name} does not exist. Creating.')
                user = Player(name)
                self.players.append(user)
                
        #find all the correct answers, building the list of points as it goes
        for answer in self.answermessages.items():
            for proof in self.active_question.answers:
                if answer[1].lower() == proof.lower():
                    self.point_dict[answer[0]] = 0
                    break
            else:
                with open(os.path.join(os.getcwd(),"config","aliases.json")) as aliases:
                    aliases = json.load(aliases)
                for name in aliases.items():
                    if answer[1].lower() in name[1] and name[0] == self.active_question.answers[0]:
                        self.point_dict[answer[0]] = 0
            for proof in self.active_question.deepcut:
                if answer[1].lower() == proof.lower():
                    self.point_dict[answer[0]] = 3
                
        #check if only 1 person answered, if so, award 3 bonus points
        for name,points in self.point_dict.items():
            if len(self.point_dict) == 1:
                self.point_dict[name] += 3
            if 1 < len(self.point_dict) < 4:
                self.point_dict[name] += 1
                
        #award 1 point for everyone, an extra point for the first 14, and another point for the first 6
        idx = 0
        for name,points in self.point_dict.items():
            if idx == 0:
                returnstr += f"{name} was the first to answer correctly."
            if idx < 6:
                self.point_dict[name] += 1
            if idx < 20:
                self.point_dict[name] += 1
            self.point_dict[name] += 1
            idx += 1
            #update the player object with the new points
            for player in self.players:
                if player.name == name:
                    player.gamepoints += self.point_dict[name]
                    player.seasonpoints += self.point_dict[name]
        self.commit_scores()
        await ws.send_privmsg(self.initial_channels[0],returnstr)
    
    
    #CHAT RESPONSES AND COMMAND FUNCTIONS
    @commands.command(name='score')
    #!score finds the score of the user sending the message and sends it in chat
    async def score(self, ctx):
        print(f'Received a score check for {ctx.author.name}') 
        if any(player.name == ctx.author.name for player in self.players):
            for player in self.players:
                if player.name == ctx.author.name:
                    print(f'Found player {player.name} with {player.gamepoints} game points and {player.seasonpoints} season points.')
                    user = player
                    if self.active_game:
                        scorestr = f"User {player.name} has {player.gamepoints} points in this game and {player.seasonpoints} for the season."
                    else:
                        scorestr = f"User {player.name} has {player.seasonpoints} points in this season."
                    break
        else:
            print(f'Player {ctx.author.name} does not exist. Creating.')
            user = Player(ctx.author.name)
            self.players.append(user)
            scorestr = f"User {user.name} has 0 points. Welcome to trivia!"
        await ctx.send(scorestr)

    @commands.command(name='raffle')
    #!raffle finds the raffle ticket count of the user sending the message and sends it in chat
    async def raffle(self, ctx):
        print(f'Received a raffle check for {ctx.author.name}') 
        if any(player.name == ctx.author.name for player in self.players):
            for player in self.players:
                if player.name == ctx.author.name:
                    rafflecount = int(player.seasonpoints/30)
                    print(f'Found player {player.name} with {player.gamepoints} game points, {player.seasonpoints} season points, and {rafflecount} raffle tickets.')
                    user = player
                    if not self.active_game:
                        scorestr = f"User {player.name} has {player.seasonpoints} for the season resulting in {rafflecount} raffle tickets."
                    break
        else:
            print(f'Player {ctx.author.name} does not exist. Creating.')
            user = Player(ctx.author.name)
            self.players.append(user)
            scorestr = f"User {user.name} has 0 points and no raffle tickets. Welcome to trivia!"
        await ctx.send(scorestr)
        
    @commands.command(name='top5')
    #!top5 returns the top5 scores for the game if a game is active or for the season if a game is not active
    async def top5(self, ctx):
        if ctx.author.name in self.admins:
            returnstr = 'TOP 5: '
            print(f'Received top 5 check from {ctx.author.name}.')
            if self.active_game:
                self.refresh_scores()
                for i in sorted(self.players, key=lambda player:player.gamepoints, reverse=True)[:5]:
                    returnstr += (f'{i.name}: {i.gamepoints}\t')
            else:
                returnstr = "THIS SEASON'S TOP 5:  "
                for i in sorted(self.players, key=lambda player:player.seasonpoints, reverse=True)[:5]:
                    returnstr += (f'{i.name}: {i.seasonpoints}\t')
            await ctx.send(returnstr)
    
    @commands.command(name='topless')
    #!topless returns the top 5 player scores for players who have not yet won a shirt as defined in pastwinners
    async def topless(self, ctx):
        if ctx.author.name in self.admins:
            returnstr = 'TOP 5 SHIRTLESS THIS '
            self.topless = []
            print(f'Received top 5 shirtless check from {ctx.author.name}.')
            self.refresh_scores()
            if self.active_game:
                returnstr += 'GAME: '
                for player in sorted(self.players, key=lambda x:x.gamepoints, reverse=True):
                    if player.name not in self.pastwinners and len(self.topless) < 5:
                        self.topless.append(player)
                        returnstr += f'{player.name}: {player.gamepoints}  '
                    else:
                        continue
            else:
                returnstr += 'SEASON: '
                for player in self.scores[f'Season {self.trivia_config["season"]}']['scoreboard'].items():
                    if player[0] not in self.pastwinners and len(self.topless) < 5:
                        self.topless.append(player[0])
                        returnstr += f'{player[0]}: {player[1]}  '
                    else:
                        continue
            await ctx.send(returnstr)

    @commands.command(name='stop')
    #!stop forces the chatbot to shut down
    async def stop(self, ctx):
        if ctx.author.name in self.admins:
            print(f'Received stop command from {ctx.author.name}.')
            if self.active_game:
                self.active_game = False
            await ctx.send('I have been commanded to stop. The Vision trivia bot is shutting down. See you next time!')
            await bot._ws.teardown()
            
    @commands.command(name='rafflewinner')
    #!rafflewinner generates a list of raffle tickets based on a person's total points/30 and selects a random winner
    async def rafflewinner(self, ctx):
        if ctx.author.name in self.admins:
            await ctx.send('This is the moment you have ALL been waiting for. The winner of the biggest prize in Stranded Panda Trivia history is...*shuffles raffle tickets for 10 seconds*')
            await asyncio.sleep(10)
            self.refresh_scores()
            with open(os.path.join(os.getcwd(),'config','scores',"scoreboard.json")) as scoreboard:
                scoreboard = json.load(scoreboard)
            scoreboard = scoreboard[f'Season {self.trivia_config["season"]}']['scoreboard']
            rafflelist = []
            for player in scoreboard.items():
                ticketcount = int(player[1]/30)
                for count in range(0,ticketcount):
                    rafflelist.append(player[0])
            drawingwinner = random.choice(rafflelist)
            await ctx.send("The hosts now have the raffle winner in their debatably capable hands...")
            print(f'The raffle winner is {drawingwinner}')
            
    @commands.command(name='seasonwinner')
    #!seasonwinner takes the top 14 scores for the season, adds them together, and produces the top 10
    async def seasonwinner(self, ctx):
        if ctx.author.name in self.admins:
            returnstr = "This season's top 10: "
            scorelists = {}
            sortedlists = {}
            finalscores = {}
            with open(os.path.join(os.getcwd(),'config','scores',"scoreboard.json")) as scoreboard:
                scoreboard = json.load(scoreboard)
            for game in scoreboard[f'Season {self.trivia_config["season"]}'].items():
                if (game[0].startswith("Game ")):
                    for player in game[1].items():
                        if player[0] not in scorelists:
                            scorelists[f'{player[0]}'] = []
                        scorelists[f'{player[0]}'].append(player[1])
            for scores in scorelists.items():
                sortedlists[f'{scores[0]}'] = sorted(scores[1],reverse=True)
            for player in sortedlists.items():
                finalscores[f'{player[0]}'] = sum(player[1][0:14])
            scoreboard = {}
            for player in sorted(finalscores.items(), key=lambda player:player[1], reverse=True):
                scoreboard[player[0]] = player[1]
            for score in sorted(scoreboard.items(), key=lambda x:x[1], reverse=True)[:10]:
                returnstr += f"{score[0]}: {score[1]}  "
            overallwinner = sorted(scoreboard.items(), key=lambda x:x[1], reverse=True)[0]
            await ctx.send("Calculating the season's winner...removing the bottom 2 scores...swapping the bonus Halloween week...")
            await asyncio.sleep(5)
            await ctx.send(f'The winner of this season of Stranded Panda Twitch Trivia is... {overallwinner[0]} with {overallwinner[1]} points!!! Congratulations {overallwinner[0]}!!!')
            await asyncio.sleep(5)
            await ctx.send(returnstr)
            
    @commands.command(name='rescore')
    #!rescore removes the most recently awarded points and rescores using the most recently submitted answer list.
    async def rescore(self, ctx):
        if ctx.author.name in self.admins and not self.questionisactive and not self.scoringopen:
            print(f"Received call for rescore from {ctx.author.name}.")
                    #update the player objects with the new points
            for name,points in self.point_dict.items():
                for player in self.players:
                    if player.name == name:
                        player.gamepoints -= points
                        player.seasonpoints -= points
            self.commit_scores()
            await self.scorequestion()
            await ctx.send("Rescoring complete.")            
            
    
            
class Question(object):
    #Each question will be an object to be added to a list of objects
    def __init__(self, question):
        badap = 'â€™'
        str_ap = "'"
        self.question = str(question[1]['Question'].replace(badap,str_ap))
        self.answers = question[1]['Answers']
        self.deepcut = question[1]['DeepCut']
        self.questionno = question[0]

class Player(object):
    #This establishes players in the current game
    def __init__(self,playername, pointstart=0):
        #if the playername variable is not a string, it's going to be a dictionary object with existing points totals.
        #The playername variable will be a string if coming from a !score command and a dictionary object if coming from bot initialization
        if not isinstance(playername, str):
            self.seasonpoints = playername[1]
            self.name = playername[0]
        else:
            self.seasonpoints = 0
            self.name = playername
        self.gamepoints = pointstart
        
if __name__ == '__main__':
    bot = ChatBot()
    bot.run()