import random
import tkinter as tk
size = 60
cellsize = 8
foodspawnper = 400
targetpop = 120

foodfromkill = 800


#the amount of cycles before the next cleanup
cleanupcycles = 60

killl = True

#the amount of central nurrons that each cell will have
nurcount = 40

#the percent out of 10000 that one nurral link gets mutated
mutatoinper = 20

#for the cells peramiters
reproducecost = 3000
foodburn =110
foodstart = 700

#the amount of food given for eating food
foodamount = 440


maincounter = 0
cycletime = 100
spos = 0
arr = {}
carr = {}
tarr = {}
started = False


#makes the entire array equal "not"
for i in range(size * 10):
    for j in range(size * 10):
        arr[i,j] = 'not'
        
for i in range(size**4):
    carr[i,0] = "not"



def clocatoinupdate(x,y,i):
    #x = x coord on arr that gets reset
    #y = y coord on arr that gets reset
    #i = index in carr that get accesed to place the cell on the map
    global arr
    global carr
    global foodamount
    if arr[carr[i,1],carr[i,2]] == "not" or arr[carr[i,1],carr[i,2]] == "food":
        if carr[i,0] == "Alive":
            if arr[carr[i,1],carr[i,2]] == "food":
                carr[i,3] = carr[i,3] + foodamount
            place(x,y,"not")
            arr[x,y] = "not"
            arr[carr[i,1],carr[i,2]] = "cell"
            place(carr[i,1],carr[i,2],str("cell" + str(i)))
            
        else:
            arr[carr[i,1],carr[i,2]] = "not"
            place(carr[i,1],carr[i,2],"not") 
    else:
        carr[i,1] = x
        carr[i,2] = y
    
    
    
        
def movec(i,di):
    #di is a number 0 - 7 witch is the directoin that the cell will move
    #i = the cell ndex
    global carr
    global arr
    x = carr[i,1]
    y = carr[i,2]
    
    if di == 0:
        carr[i,1] = x + 1
    if di == 1:
        carr[i,1] = x + 1
        carr[i,2] = y + 1
    if di == 2:
        carr[i,2] = y + 1
    if di == 3:
        carr[i,1] = x - 1
        carr[i,2] = y + 1  
    if di == 4:
        carr[i,1] = x - 1
    if di == 5:
        carr[i,1] = x - 1
        carr[i,2] = y - 1
    if di == 6:
        carr[i,2] = y - 1
    if di == 7:
        carr[i,1] = x + 1
        carr[i,2] = y - 1
        
    clocatoinupdate(x,y,i)
    
        
# gose to every point and has a "per" percent chance of placeing a dot
def placefoodrandom(per):
    global arr
    global size
    #print(str(per))
    for x in range(size):
        for y in range(size):
            m = random.randint(1, 1000)
            #print(str(m))
            if per >= m and arr[x,y] == "not":
                #print(str(m) + "_______________________________________________________________")
                place(x,y,"food")
                
def placewallrandom(per):
    global arr
    global size
    for x in range(size):
        for y in range(size):
            if per >= random.randint(1, 100):
                place(x,y,"wall")
                
def wallgen(randomper,spawnsides,killsides,times):
    global arr
    global size
    
    placewallrandom(randomper)
    for i in range(times):
        wallrounder(spawnsides,killsides)

    
    
    
def wallrounder(spawnsides,killsides):
    global arr
    global size
    parr = {}
    for x in range(size):
        for y in range(size):
            if x == 0 or x == size - 1:
                arr[x,y] = "wall"
                parr[x,y] = "wall"
            elif y == 0 or y == size - 1:
                arr[x,y] = "wall"
                parr[x,y] = "wall"
            else:
                if sidecounter(x,y,"wall") <= killsides:
                    parr[x,y] = "not"
                elif sidecounter(x,y,"wall") >= spawnsides:
                    parr[x,y] = "wall"
                else:
                    parr[x,y] = arr[x,y]
    for x in range(size):
        for y in range(size):
            arr[x,y] = parr[x,y]
        

def placefoodrnadom(randomper):
    for x in range(size):
        for y in range(size):
            if arr[x,y] != "wall":
                if randomper >= random.randint(1, 100):
                    place(x,y,"food")
    
        
def sidecounter(x,y,s):
    global arr
    z = 0
    if arr[x,y + 1] == s:
        z = z + 1
    if arr[x + 1,y + 1] == s:
        z = z + 1
    if arr[x + 1,y] == s:
        z = z + 1
    if arr[x + 1,y - 1] == s:
        z = z + 1
    if arr[x,y - 1] == s:
        z = z + 1
    if arr[x - 1,y - 1] == s:
        z = z + 1
    if arr[x - 1,y] == s:
        z = z + 1
    if arr[x - 1,y + 1] == s:
        z = z + 1

    return z
    
    

def place(x,y,tp):
    global arr
    #places something on the map at the x y coords of type given
    desplay.delete(x * cellsize,y* cellsize,x* cellsize + cellsize ,y* cellsize + cellsize)
    if len(tp) > 4:
        i = tp[4:int(len(tp))]
        tp = tp[0:4]
        desplay.create_rectangle(x * cellsize,y* cellsize,x* cellsize + cellsize ,y* cellsize + cellsize, fill = cellcolorlocator(i))

    else:
        arr[x,y] = str(tp)
        color = colorlocator(str(tp))
        desplay.create_rectangle(x * cellsize,y* cellsize,x* cellsize + cellsize ,y* cellsize + cellsize,fill = color )
        

def cellcolorlocator(i):
    global carr
    x = carr[int(i),6]
    #print(x)
    return x
    


def colorlocator(s):
    if s == "wall":
        return "gray"
    if s == "cell":
        return "red"
    if s == "food":
        return "limegreen"
    return "white"

    
    

def makedes():
    global arr
    global cellsize
    #desplayes
    desplay.delete("all")
    for x in range(0,size * cellsize,cellsize):
        for y in range(0,size * cellsize,cellsize):
    
            accx = int(round(x/cellsize))
            accy = int(round(y/cellsize))
            if arr[accx,accy] == "food":
                desplay.create_rectangle(x,y,x + cellsize ,y + cellsize,fill = colorlocator(arr[accx,accy]) )
                window.update
            if arr[accx,accy] == "wall":
                desplay.create_rectangle(x,y,x + cellsize ,y + cellsize,fill = colorlocator(arr[accx,accy]) )
                window.update
            if arr[accx,accy] == "cell":
                desplay.create_rectangle(x,y,x + cellsize ,y + cellsize,fill = colorlocator(arr[accx,accy]) )
                window.update
            if arr[accx,accy] == "not":
                desplay.create_rectangle(x,y,x + cellsize ,y + cellsize,fill = colorlocator(arr[accx,accy]) )
                window.update
            
                
                



def digg(number,n):
    return number // 10**n % 10






def mapmaker(seed):
    for i in range(size):
        for j in range(size):
            arr[i,j] = 'not'
    #biulds a map useing the seed given
    wallgen((digg(seed,0))+digg(seed,9),digg(seed,1),digg(seed,2),digg(seed,3))
    for i in range(1):
        for i in range(digg(seed,4)):
            wallrounder(digg(seed,6),digg(seed,7))
            
def mappercent():
    #finds that percent of the entire map that is = to "not"
    global arr
    global size
    z = 0
    for x in range(size):
        for y in range(size):
            if arr[x,y] == "not":
                z = z + 1
    return (z/(size**2)) * 100

def foodmappercent():
    global arr
    global size
    z = 0
    for x in range(size):
        for y in range(size):
            if arr[x,y] == "food":
                z = z + 1
    return (z/(size**2) * int(round(mappercent()/100)) * 100)

def mapfinder(landper):
    #will find a seed that has landper % land 
    seed = random.randint(100000000000,999999999999)
    bestseed = seed
    landperoff = 100
    varamount = 1
    miscount = 0
    while True:
        mapmaker(seed)
        if mappercent() < landper + 6 and mappercent() > landper - 6:
            print("___found______________________________________________________________  " + str(seed))
            return int(seed)
        elif abs(landper - mappercent()) < landperoff:
            landperoff = abs(landper - mappercent())
            varamount = 1
            misscount = 0
            print(str(seed) + "  found new best  " + str(landperoff))
            bestseed = seed
            seed = seed + ((10 ** random.randint(0,8)) * random.randint(-1 * varamount,varamount))
        else:
            seed = bestseed + ((10 ** random.randint(0,8)) * random.randint(-1 * varamount,varamount))
            misscount = misscount + 1
            if misscount == 2:
                misscount = 0
                varamount = varamount + 1
            if varamount == 8:
                seed = random.randint(100000000000,999999999999)
                bestseed = seed
                varamount = 1
                misscount = 0
                landperoff = 100
                
                
def findseeds(x,n):
    #will locate x number of seeds with n % land 
    sarr = {}
    for i in range(x):
        sarr[i] = mapfinder(n)
        print(str(i) + "|||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||")
    for i in range(x):
        print("____________________________________________________________________")
        print(str(sarr[i]))
       
#943023794355 
#mapmaker(439949945218)
def seedchaoschecker(chunkamount,choselevel,landper):
    # returns the percent of chunks that have landper % land + or - choaslevel
    global size
    z = 0
    for x in range(round(chunkamount)):
        for y in range(round(chunkamount)):
            print(str(chunkpercent(x,y,chunkamount)))
            if chunkpercent(x,y,chunkamount) > landper - choselevel and chunkpercent(x,y,chunkamount) <  landper + choselevel:
                z = z + 1
    return z / (chunkamount**2) * 100
    
def chunkpercent(chunkx,chunky,chunksize):
    global arr
    z = 0
    for x in range(round(size/chunksize)):
        for y in range(round(size/chunksize)):
            if arr[x + (chunkx * round(size/chunksize)),y + (chunky * round(size/chunksize))] == "not":
                z = z + 1
    return (z/(round(size/chunksize)**2)) * 100
    
    

    
    
        
def sprint(s):
    global size
    global cellsize
    global spos
    if spos > int((size * cellsize)/20) - 1:
        spos = 0
        shell.delete (0,100)
    shell.insert(spos,s)
    spos = spos + 1
    
def seedfindermain(landper,checked,varamount,detail,n):
    sarr = {}
    for i in range(checked):
        seed2 = mapfinder(landper)
        mapmaker(seed2)
        sarr[i] = seed2
        if seedchaoschecker(detail,varamount,landper) > n:
            sarr[i] = str(str(seed2) + "----------------")
            print("good")
    print("____________________________________________________________________")
    for i in range(checked):
        try:
            print(str(sarr[i]))
        except:
            print("--")


def foodgen(randomper,outreach,spawnper,times,multiplyer):
    global arr
    global size
    if times > 2 or times == 0:
        times = 1
    placefoodrandom(int(randomper))
    for i in range(times):
        foodspreader(outreach,spawnper,multiplyer)
        
def foodspreader(outreach,spawnper,multiplyer):
    marr = {}
    global arr
    global size
    for i in range(size):
        for j in range(size):
            marr[i,j] = 'not'
    
    for x in range(size):
        for y in range(size):
            if arr[x,y] == "food":
                for x2 in range (-1 * outreach,outreach,1):
                    for y2 in range (-1 * outreach,outreach,1): 
                        n = random.randint(0,100)
                        if x + x2 > 0 and y + y2 > 0 and x + x2 < size and y + y2 < size:
                            m = abs(int(biggest(x2,y2)))
                            #print(str((m + 1) * multiplyer))
                            try:
                                if spawnper > random.randint(1,(m + 1) * (multiplyer + 1)):
                                    xn = int(x + x2)
                                    yn = int(y + y2)
                                    #print(str(xn) + "---" + str(yn))
                                    marr[xn,yn] = "food"
                            except:
                                print(str((m + 1) * multiplyer) + "_-_-_-_-_-_-_-_-_-_-_-_-_-_-_-")
                                if spawnper > random.randint(1,100):
                                    xn = int(x + x2)
                                    yn = int(y + y2)
                                    #print(str(xn) + "---" + str(yn))
                                    marr[xn,yn] = "food"
                                
                                
                                
    for x in range(size):
        for y in range(size):
            if marr[x,y] == "food" and arr[x,y] == "not":
                arr[x,y] = marr[x,y]
                

def foodmaker(seed):
    global arr
    for x in range(size):
        for y in range(size):
            if arr[x,y] == "food":
                arr[x,y] = "not"
    foodgen((digg(seed,0) * 10) + digg(seed,1),digg(seed,2),(digg(seed,3) * 10) + digg(seed,4),digg(seed,5),(digg(seed,6) * 10) + digg(seed,7))
                
    
def biggest(x,y):
    if x < y:
        return y
    else:
        return x
    
def foodmapfinder(landper):
    #will find a seed that has landper % land 
    seed = random.randint(1000000000,9999999999)
    bestseed = seed
    landperoff = 100
    varamount = 1
    miscount = 0
    while True:
        print(str(seed))
        foodmaker(seed)
        if foodmappercent() < landper + 6 and foodmappercent() > landper - 6:
            print("___found______________________________________________________________  " + str(seed))
            return int(seed)
        elif abs(landper - foodmappercent()) < landperoff:
            landperoff = abs(landper - foodmappercent())
            varamount = 1
            misscount = 0
            print(str(seed) + "  found new best  " + str(landperoff))
            bestseed = seed
            seed = seed + ((10 ** random.randint(0,8)) * random.randint(-1 * varamount,varamount))
        else:
            seed = bestseed + ((10 ** random.randint(0,8)) * random.randint(-1 * varamount,varamount))
            misscount = misscount + 1
            if misscount == 3:
                misscount = 0
                varamount = varamount + 1
            if varamount == 5:
                seed = random.randint(100000000000,999999999999)
                bestseed = seed
                varamount = 1
                misscount = 0
                landperoff = 100

def foodseedchaoschecker(chunkamount,choselevel,landper):
    # returns the percent of chunks that have landper % land + or - choaslevel
    global size
    z = 0
    for x in range(round(chunkamount)):
        for y in range(round(chunkamount)):
            print(str(foodchunkpercent(x,y,chunkamount)))
            if foodchunkpercent(x,y,chunkamount) > landper - choselevel and foodchunkpercent(x,y,chunkamount) <  landper + choselevel:
                z = z + 1
    return z / (chunkamount**2) * 100
    
def foodchunkpercent(chunkx,chunky,chunksize):
    global arr
    z = 0
    for x in range(round(size/chunksize)):
        for y in range(round(size/chunksize)):
            if arr[x + (chunkx * round(size/chunksize)),y + (chunky * round(size/chunksize))] == "food":
                z = z + 1
    return (z/(round(size/chunksize)**2)) * 100
    
    
    



def foodmapmain(landper,checked,varamount,detail,n):
    sarr = {}
    for i in range(checked):
        seed2 = foodmapfinder(landper)
        foodmaker(seed2)
        m = foodseedchaoschecker(detail,varamount,landper)
        sarr[i] = str(str(seed2) + "---" + str(m))
        if m > n:
            sarr[i] = str(str(seed2) + "----------------"  + str(m))
            print("good")
    print("____________________________________________________________________")
    for i in range(checked):
        try:
            print(str(sarr[i]))
        except:
            print("--")
            

def reproduce(i):
    global reproducecost
    global carr
    global arr
    global foodburn
    global foodstart
    #print("reproduce" + str(carr[i,3]))
    if carr[i,3] >= reproducecost:
        carr[i,3] = carr[i,3] - reproducecost

        p = 0
        while True:
            xmod = random.randint(-2,2)
            ymod = random.randint(-2,2)
            if ymod != 0 or xmod != 0:
                x = carr[i,1] + xmod
                y = carr[i,2] + ymod
                if x > 0 and y > 0 and x < size and y < size:
                    if arr[x,y] == "food" or arr[x,y] == "not":
                        #print(str(x) + str(y))
                        makec(x,y,foodstart,foodburn,i)
                        break
            p = p + 1
            if p > 500:
                break

    
    
def kill(mainindex):
    global foodfromkill
    global carr
    global arr
    global killl
    i = 0
    if sidecounter(carr[mainindex,1],carr[mainindex,2],"cell") > 0 and killl:
        while True:
            #print(str(i) + "index being killed")
            if carr[i,0] == "Alive":
                if mainindex != i and carr[i,1] >= carr[mainindex,1] - 1 and carr[i,1] <= carr[mainindex,1] + 1 and carr[i,2] >= carr[mainindex,2] - 1 and carr[i,2] <= carr[mainindex,2] + 1:
                    carr[i,0] = "dead"
                    carr[mainindex,3] = carr[mainindex,3] + foodfromkill
                    sprint("kill----" + str(mainindex))
                    arr[carr[i,1],carr[i,2]] = "not"
                    clocatoinupdate(1,2,i)
                    
            elif carr[i,0] == "not":
                break
            i = i + 1
            
def minn(x,n):
    if x < n:
        return n
    return x
            
def foodspawner():
    global foodspawnper
    global size
    global arr
    for x in range(size):
        for y in range(size):
            if foodspawnper > random.randint(0,10000):
                if arr[x,y] == "not":
                    place(x,y,"food")
                    
                    

        
def foodspawnadj(cellamount):
    global targetpop
    global foodspawnper
    #print(str(cellamount - targetpop))
    #print(str(cellamount))
    foodspawnper = minn(foodspawnper - int(round((cellamount - targetpop)/5)),0)
    #print(foodspawnper)
    
    
    
    
def makec(x,y,foodstart,foodburn,parentindex):
    global arr
    global carr
    global mutatoinper
    colorarr = ["pink","blue","yellow","red","purple","lime","lightblue","orange","darkred","darkblue","darkgreen","hotpink","#1A1B55","#0C10FF","#E0FF0C","#2EC691","#C6592E","#9AECF4","#D19AF4","#6C1AA0","#FF00CA","#674F62","#57FF00","brown"]
    i = 0
    place(x,y,"cell")
    while True:
        if carr[i,0] == "not":
        
            #0 = state(alive,dead)
            #1 = x
            #2 = y
            #3 = amount of food that u start with
            #4 = food buned per turn
            #5 = brain config
            carr[i,0] = "Alive"
            carr[i,1] = x
            carr[i,2] = y
            carr[i,3] = foodstart
            carr[i,4] = foodburn
            
            
            
            if parentindex == "not":
                carr[i,6] = colorarr[random.randint(0,len(colorarr) - 1)]
                #print(str(carr[i,6]))
                
                for midindex in range(nurcount):
                    for inpindex in range(25):
                        carr[i,5,0,inpindex,midindex] = 0 #(random.randint(-9,9)/100) + (random.randint(-2,2)/100)
                        
                        
                for outindex in range(9):
                    for midindex in range(nurcount):
                        carr[i,5,1,midindex,outindex] = 0 #(random.randint(-9,9)/100) + (random.randint(-2,2)/100)
                        
                for h in range(9):    #change starting smarts here--------------------------------------
                    m1 = 0
                    m2 = 0
                    m = 0
                    for midindex in range(nurcount):
                        for inpindex in range(25):
                            #print(str(carr[i,5,0,inpindex,midindex]))
                            r = random.randint(0,10000)
                            if r < mutatoinper:
                                m1 = random.randint(-9,9)
                                m2 = random.choice([-1,0,0,0,0,0,0,0,1])
                                m = m1/100 + m2 / 10
                            else:
                                m1 = 0
                                m2 = 0
                                m = 0
                                
                                
                                
                                #print(m)
                                
                            carr[i,5,0,inpindex,midindex] = m + carr[i,5,0,inpindex,midindex]
                            #print(str(carr[i,5,0,inpindex,midindex]))
                            m1 = 0
                            m2 = 0
                            m = 0
                    for outindex in range(9):
                        for midindex in range(nurcount):
                             r = random.randint(0,10000)
                             if r < mutatoinper:
                                 m1 = random.randint(-9,9)
                                 m2 = random.choice([-1,0,0,0,0,0,1])
                                
                                 m = m1/100 + m2 / 10
                                 #print(m)
                             else:
                                m1 = 0
                                m2 = 0
                                m = 0
                                
                             carr[i,5,1,midindex,outindex] = m + carr[i,5,1,midindex,outindex]
                             m1 = 0
                             m2 = 0
                             m = 0
            
            else:
                if random.randint(0,40) == 3:
                    carr[i,6] = colorarr[random.randint(0,len(colorarr) - 1)]
                else:
                    carr[i,6] = carr[parentindex,6]
                m1 = 0
                m2 = 0
                m = 0
                m0 = 0
                for midindex in range(nurcount):
                    for inpindex in range(25):
                        r = random.randint(0,10000)
                        if r < mutatoinper:
                            m0 = random.randint(-9,9)
                            m1 = random.randint(-3,3)
                            m2 = random.choice([-1,0,0,0,0,0,0,0,1])
                            
                            m = m1/100 + m2 / 10 + m0 /1000
                            #print(m)
                            
                        carr[i,5,0,inpindex,midindex] = m + carr[parentindex,5,0,inpindex,midindex]
                        m1 = 0
                        m2 = 0
                        m = 0
                        m0 = 0
                for outindex in range(9):
                    for midindex in range(nurcount):
                         r = random.randint(0,10000)
                         if r < mutatoinper:
                             m1 = random.randint(-9,9)
                             m2 = random.choice([-1,0,0,0,0,0,1])
                            
                             m = m1/100 + m2 / 10
                             #print(m)
                            
                         carr[i,5,1,midindex,outindex] = m + carr[parentindex,5,1,midindex,outindex]
                         m1 = 0
                         m2 = 0
                         m = 0
            arr[x,y] = "cell"
            break
        
        i = i + 1
        

def brain(i):
    global carr
    global arr
    if carr[i,3] > reproducecost + (carr[i,4] * 3):
        return 9
    inp = {}
    cellx = carr[i,1]
    celly = carr[i,2]
    #get all the values for the input nurons and stors them in a arr called inp
    count = 0
    for xmod in range(-2,3,1):
        for ymod in range(-2,3,1):
            x = cellx + xmod
            y = celly + ymod
            if x > 0 and x < size and y > 0 and y < size:
                if arr[x,y] == "cell":
                    inp[count] = 0
                elif arr[x,y] == "wall":
                    inp[count] = 0
                elif arr[x,y] == "not":
                    inp[count] = 300
                elif arr[x,y] == "food":
                    inp[count] = 1000
            else:
                inp[count] = 333
            #print(ymod)
            count = count + 1
    global nurcount
    mid = {}
    for midindex in range(nurcount):
        mid[midindex] = 0#replac with modifyer
        for inpindex in range(25): #25 = 5 * 5 (the amount of input nurrons)
            #print(str(inpindex) + "-" + str(midindex))
            #print(str(carr[i,5,0,inpindex,midindex]))
            mid[midindex] = mid[midindex] + int(round(inp[inpindex] * carr[i,5,0,inpindex,midindex]))#replace with a number gathered from the brain seed
        squisher(mid[midindex])
    
    out = {}
    for outindex in range(9):
        out[outindex] = 0#replac with modifyer
        for midindex in range(nurcount):
            out[outindex] = out[outindex] + int(round(mid[midindex] * carr[i,5,1,midindex,outindex]))
     
    x = 0
    for outindex in range(9):
        if out[outindex] > out[x]:
            x = outindex
    return x
        
        
    return random.randint(0,9)


def spawnperupdate(x):
    global foodspawnper
    foodspawnper = int(x)
    
def squisher(x):
    if x < 0:
        return 0
    if x > 1000:
        return 1000
    return x
            
            
def carradj():
    global maincounter
    global carr
    global nurcount
    global tarr
    global cleanupcycles
    parr = {}
    i = 0
    count = 0
    while True:
        if carr[i,0] == "Alive":
            carr[count,6] = carr[i,6]
            for j in range(4): 
                parr[count,j] = carr[i,j]
                
                
            for outindex in range(9):
                for midindex in range(nurcount):
                    parr[count,5,1,midindex,outindex] = carr[count,5,1,midindex,outindex]
            
            
            
            for midindex in range(nurcount):
                for inpindex in range(25):
                    parr[count,5,0,inpindex,midindex] = carr[count,5,0,inpindex,midindex]
                        
                        
            count = count + 1
        elif carr[i,0] == "not":
            break
        i = i + 1
    for k in range(count):
        for j in range(4):  
            carr[k,j] = parr[k,j]
            
        for outindex in range(9):
            for midindex in range(nurcount):
                carr[k,5,1,midindex,outindex] = parr[k,5,1,midindex,outindex]
            
            
            
        for midindex in range(nurcount):
            for inpindex in range(25):
                carr[k,5,0,inpindex,midindex] = parr[k,5,0,inpindex,midindex]
        
    print("===")
    for l in range(i - count):
        carr[count + l,0] = "not"
        print(count + l)
        
    
        
        
    tarr[int(maincounter / cleanupcycles)] = count
    if int(maincounter / cleanupcycles) >  1:
        deaths = i - count
        print('b')
        change = tarr[int(maincounter / cleanupcycles)] - tarr[int(maincounter / cleanupcycles) - 1]
        births = deaths + change
        sprint(str("change: " + str(change)))
        sprint(str("deaths: " + str(deaths)))
        sprint(str("births: " + str(births)))
        sprint(str("alive: " + str(i)))
        print("12222222222222222222")
        #print(str(carr[count + l,0]))
    #print(str(count) + "--------909090900000000000000000000000000000000000000000099999999999999999999999999")

def run():
    global cycletime
    global spos
    global started
    global size
    global foodstart
    global foodburn
    for i in range(size):
        for j in range(size):
            arr[i,j] = 'not'
    for i in range(size**2):
        carr[i,0] = "not"
    mapseed = seedentry.get()
    foodseed = foodseedentry.get()
    cycletime = cycletimetimeentry.get()
    mapmaker(int(mapseed))
    foodmaker(int(foodseed))
    started = True
    
    for i in range(1):
        while True:
            x = random.randint(2,size - 2)
            y = random.randint(2,size - 2)
            if arr[x,y] == "food" or arr[x,y] == "not":
                makec(x,y,206000,foodburn,"not")
                break



    makedes()
    sprint("started")
    
def main():
    global maincounter
    global carr
    global cycletime
    global started
    global cleanupcycles
    if started:
        foodspawner()
        #print(str(carr[3,3]) + "-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=")
        i = 0
        a = 0
        while True:
            #print(str(i) + "-------")
            if carr[i,0] == "Alive":
                a = a + 1
                carr[i,3] = carr[i,3] - carr[i,4]
                if carr[i,3] < 0:
                    carr[i,0] = "dead"
                    arr[carr[i,1],carr[i,2]] = "not"
                    clocatoinupdate(1,2,i)
                n = brain(i)
                if n <= 7:
                    movec(i,n)
                elif n == 9:
                    reproduce(i)
                elif n == 8:
                    kill(i)
            elif carr[i,0] == "not":
                if a < 1:
                    
                    run()
                #if (maincounter / 4) % 1 == 0:
                    #foodspawnadj(a)
                break
                #print(str(carr[i,0]))
            #print(str(i))
            i = i + 1
            if i > 1000000:
                break
        if (maincounter / cleanupcycles) % 1 == 0:
            #carradj()
            makedes()
        maincounter = maincounter + 1
        sprint(str(maincounter))
    ticker.after(cycletime,main)
    


    
def muupdate(x):
    global mutatoinper
    mutatoinper = int(x)

#foodmapmain(20,20,10,5,70)
    
    
    
#foodmapfinder(20)

#print(seedchaoschecker(4,15,73))
    
#findseeds(10,65)
#foodgen(30)


#makec(size - 1,size - 1,50,1,1212)
#clocatoinupdate(2,2,0)

#mapmaker(940601987458)
#print(str(mappercent()))



#creats windon ect
mapsise = str(size * (cellsize) + 452) + "x" + str(size * (cellsize) + 400)
window = tk.Tk()
window.title("sim")
window.geometry(mapsise)

ticker = tk.Label(window,text = "e", width = 20 , height = 1)


startbutton = tk.Button(window,text = "start", width = 10 , height = 1,command = run)


seedentry = tk.Entry(window,width = 30)
seedlabel = tk.Label(window,text = "mapseed", width = 20 , height = 1)

foodseedentry = tk.Entry(window,width = 30)
foodseedlabel = tk.Label(window,text = "foodseed", width = 20 , height = 1)

cycletimetimeentry = tk.Entry(window,width = 30)
cycletimelabel = tk.Label(window,text = "cycle ms", width = 20 , height = 1)

desplay = tk.Canvas(height=size * cellsize, width=size * cellsize,bg = "black")


shell = tk.Listbox(window, height = int((size * cellsize)/22), width = 40)

mainslider = tk.Scale(from_ = 0, to = 1000, length= 600,command = spawnperupdate)

muslider = tk.Scale(from_ = 0, to = 1000, length= 600,command = muupdate)


muslider.grid(column = 3 ,row = 0)
mainslider.grid(column = 2 ,row = 0)
startbutton.grid(column = 0 ,row = 1)
seedlabel.grid(column = 0 ,row = 2)
seedentry.grid(column = 0 ,row = 3)
foodseedlabel.grid(column = 0 ,row = 4)
foodseedentry.grid(column = 0 ,row = 5)
desplay.grid(column = 0 ,row = 0)
shell.grid(column = 1 ,row = 0)
cycletimetimeentry.grid(column = 0 ,row = 7)
cycletimelabel.grid(column = 0 ,row = 6)


cycletimetimeentry.insert(0,str(100))
seedentry.insert(0,str(904885159962))
foodseedentry.insert(0,str(7240199706))
main()
#seedfindermain(55,10,15,8,37)

window.mainloop()